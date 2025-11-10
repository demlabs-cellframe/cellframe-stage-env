"""
Reusable intelligent waiters for common operations.

Provides waiters for:
- UTXO indexation in ledger_items
- Chain files reload completion
- Transaction history updates
- Container restart completion
"""

import asyncio
import re
import time
from typing import Optional, Callable, List

from ..utils.logger import get_logger
from .base import BaseWaiter


logger = get_logger(__name__)


class LedgerTransactionWaiter(BaseWaiter):
    """
    Waits for a transaction (datum) to appear in ledger using `ledger info`.
    
    This waiter uses `ledger info -hash <datum_hash>` which checks ledger_items
    directly, unlike tx_history which depends on PVT(a_dag)->datums being populated.
    
    Usage:
        waiter = LedgerTransactionWaiter(exec_cli_func, node_id, datum_hash, network)
        await waiter.wait(timeout=30.0, name="ledger_transaction")
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        datum_hash: str,
        network: str = "stagenet",
        poll_interval: float = 1.0
    ):
        """
        Initialize ledger transaction waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node_id: Node ID to check
            datum_hash: Datum hash (transaction hash) to wait for
            network: Network name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.datum_hash = datum_hash
        self.network = network
    
    async def check(self) -> bool:
        """
        Check if transaction is present in ledger.
        
        Returns:
            True if transaction found in ledger
        """
        try:
            exit_code, stdout, stderr = self.exec_cli(
                self.node_id,
                f"ledger info -net {self.network} -hash {self.datum_hash}",
                check_output=False
            )
            
            if exit_code != 0:
                return False
            
            # Check if datum hash is present in output
            if stdout and self.datum_hash.lower() in stdout.lower():
                # Also check for "Datum_tx_hash" or similar indicators
                if "Datum_tx_hash" in stdout or "datum" in stdout.lower():
                    logger.debug("ledger_transaction_found",
                               node_id=self.node_id,
                               datum_hash=self.datum_hash[:16],
                               note="Transaction found in ledger")
                    return True
            
            return False
            
        except Exception as e:
            logger.warning("ledger_transaction_check_failed",
                         node_id=self.node_id,
                         datum_hash=self.datum_hash[:16],
                         error=str(e))
            return False


class UTXOIndexationWaiter(BaseWaiter):
    """
    DEPRECATED: Use LedgerTransactionWaiter instead.
    
    Waits for UTXO to be indexed in ledger_items (tx_history becomes non-empty).
    
    This waiter is deprecated because tx_history depends on PVT(a_dag)->datums
    which may not be populated after snapshot restore. Use LedgerTransactionWaiter
    with specific datum hashes instead.
    
    Usage:
        waiter = UTXOIndexationWaiter(exec_cli_func, node_id, wallet_addr, network, chain)
        await waiter.wait(timeout=30.0, name="utxo_indexation")
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        wallet_addr: str,
        network: str = "stagenet",
        chain: str = "zerochain",
        poll_interval: float = 1.0
    ):
        """
        Initialize UTXO indexation waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node_id: Node ID to check
            wallet_addr: Wallet address to check tx_history for
            network: Network name
            chain: Chain name  
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.wallet_addr = wallet_addr
        self.network = network
        self.chain = chain
    
    async def check(self) -> bool:
        """
        Check if UTXO are indexed by checking tx_history.
        
        Returns:
            True if tx_history is not empty
        """
        try:
            # WORKAROUND: Use -head flag to force forward iteration (get_first/get_next)
            # because DAG chains don't implement get_last/get_prev callbacks
            exit_code, stdout, stderr = self.exec_cli(
                self.node_id,
                f"tx_history -addr {self.wallet_addr} -net {self.network} -chain {self.chain} -head",
                check_output=False
            )
            
            if exit_code == 0 and stdout:
                # Check if tx_history is not empty
                if "status: empty" not in stdout.lower():
                    # Check for total_tx_count > 0
                    tx_count_match = re.search(r'total_tx_count:\s*(\d+)', stdout, re.IGNORECASE)
                    if tx_count_match and int(tx_count_match.group(1)) > 0:
                        logger.debug("utxo_indexed_check_passed",
                                   node_id=self.node_id,
                                   tx_count=tx_count_match.group(1),
                                   wallet_addr=self.wallet_addr[:16])
                        return True
            
            return False
            
        except Exception as e:
            logger.warning("utxo_indexation_check_failed",
                         node_id=self.node_id,
                         error=str(e))
            return False


class ChainReloadWaiter(BaseWaiter):
    """
    Waits for nodes to complete startup and chain files reload.
    
    Checks nodes are online and responsive to CLI commands.
    
    Usage:
        waiter = ChainReloadWaiter(state_manager, nodes)
        await waiter.wait(timeout=30.0, name="chain_reload")
    """
    
    def __init__(
        self,
        state_manager,
        nodes: List,
        poll_interval: float = 1.0
    ):
        """
        Initialize chain reload waiter.
        
        Args:
            state_manager: NodeStateManager instance
            nodes: List of nodes to check
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.state_manager = state_manager
        self.nodes = nodes
        self._online_checked = False
    
    async def check(self) -> bool:
        """
        Check if nodes are online and chain is loaded.
        
        Returns:
            True if all nodes are online
        """
        try:
            if not self._online_checked:
                # Check if nodes are online
                await self.state_manager.wait_for_nodes_online(
                    self.nodes, 
                    timeout=60.0
                )
                self._online_checked = True
            
            # If we got here, nodes are online
            return True
            
        except Exception as e:
            logger.warning("chain_reload_check_failed", error=str(e))
            return False


class NetworkOnlineWaiter(BaseWaiter):
    """
    Waits for network to reach NET_STATE_ONLINE.
    
    After restart, network goes through states:
    OFFLINE -> LINKS_PREPARE -> LINKS_CONNECTING -> LINKS_ESTABLISHED -> ONLINE
    
    Usage:
        waiter = NetworkOnlineWaiter(exec_cli_func, node_id, network)
        await waiter.wait(timeout=60.0, name="network_online")
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        network: str = "stagenet",
        poll_interval: float = 1.0
    ):
        """
        Initialize network online waiter.
        
        Args:
            exec_cli: CLI execution function
            node_id: Node ID to check
            network: Network name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.network = network
    
    async def check(self) -> bool:
        """
        Check if network is in ONLINE state.
        
        Returns:
            True if network state is NET_STATE_ONLINE
        """
        try:
            exit_code, stdout, stderr = self.exec_cli(
                self.node_id,
                f"net -net {self.network} get status",
                check_output=False
            )
            
            if exit_code == 0 and stdout:
                if "NET_STATE_ONLINE" in stdout:
                    logger.debug("network_online_state_reached",
                               node_id=self.node_id)
                    return True
            
            return False
            
        except Exception as e:
            logger.warning("network_online_check_failed",
                         node_id=self.node_id,
                         error=str(e))
            return False


class NetworkSyncCompletionWaiter(BaseWaiter):
    """
    Waits for network sync to complete (NET_STATE_SYNC_CHAINS -> NET_STATE_ONLINE).
    
    After calling 'net go sync', network transitions:
    1. NET_STATE_ONLINE -> NET_STATE_OFFLINE (goes offline to reset)
    2. NET_STATE_OFFLINE -> NET_STATE_SYNC_CHAINS (sync starts)
    3. NET_STATE_SYNC_CHAINS -> NET_STATE_ONLINE (sync completes)
    
    During NET_STATE_SYNC_CHAINS, SDK indexes UTXO into ledger_items!
    
    This waiter handles all intermediate states (OFFLINE, LINKS_CONNECTING, etc.)
    and waits for the complete cycle to finish.
    
    Usage:
        waiter = NetworkSyncCompletionWaiter(exec_cli_func, node_id, network)
        await waiter.wait(timeout=120.0, name="network_sync_completion")
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        network: str = "stagenet",
        poll_interval: float = 1.0
    ):
        """
        Initialize network sync completion waiter.
        
        Args:
            exec_cli: CLI execution function
            node_id: Node ID to check
            network: Network name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.network = network
        self._sync_started = False
    
    async def check(self) -> bool:
        """
        Check if network sync has completed.
        
        Returns:
            True if network returned to ONLINE state after SYNC_CHAINS
        """
        try:
            exit_code, stdout, stderr = self.exec_cli(
                self.node_id,
                f"net -net {self.network} get status",
                check_output=False
            )
            
            if exit_code == 0 and stdout:
                # Log current state for debugging
                current_state = "UNKNOWN"
                if "NET_STATE_OFFLINE" in stdout:
                    current_state = "NET_STATE_OFFLINE"
                elif "NET_STATE_SYNC_CHAINS" in stdout:
                    current_state = "NET_STATE_SYNC_CHAINS"
                elif "NET_STATE_ONLINE" in stdout:
                    current_state = "NET_STATE_ONLINE"
                elif "NET_STATE_LINKS_CONNECTING" in stdout:
                    current_state = "NET_STATE_LINKS_CONNECTING"
                elif "NET_STATE_LINKS_PREPARE" in stdout:
                    current_state = "NET_STATE_LINKS_PREPARE"
                
                # Check current network state
                if "NET_STATE_OFFLINE" in stdout:
                    # Network is offline - this happens after 'net go sync' before sync starts
                    # Wait for transition to SYNC_CHAINS
                    logger.debug("network_sync_waiting_for_sync_chains",
                               node_id=self.node_id,
                               current_state=current_state,
                               note="Network is OFFLINE - waiting for transition to SYNC_CHAINS")
                    return False
                elif "NET_STATE_SYNC_CHAINS" in stdout:
                    # Sync is in progress - UTXO indexation happens here
                    self._sync_started = True
                    logger.debug("network_sync_in_progress",
                               node_id=self.node_id,
                               current_state=current_state,
                               note="Network is in SYNC_CHAINS state - UTXO indexation in progress")
                    return False
                elif "NET_STATE_ONLINE" in stdout and self._sync_started:
                    # Sync completed - network returned to ONLINE after SYNC_CHAINS
                    logger.debug("network_sync_completed",
                               node_id=self.node_id,
                               current_state=current_state,
                               note="Network returned to ONLINE after SYNC_CHAINS - UTXO should be indexed")
                    return True
                elif "NET_STATE_ONLINE" in stdout:
                    # Still online, sync hasn't started yet
                    logger.debug("network_sync_waiting_for_sync_start",
                               node_id=self.node_id,
                               current_state=current_state,
                               note="Network is ONLINE but sync hasn't started yet")
                    return False
                elif "NET_STATE_LINKS_CONNECTING" in stdout or "NET_STATE_LINKS_PREPARE" in stdout:
                    # Network is connecting - wait for it to stabilize
                    logger.debug("network_sync_waiting_for_links",
                               node_id=self.node_id,
                               current_state=current_state,
                               note="Network is connecting links - waiting for stable state")
                    return False
                else:
                    # Unknown state - log for debugging
                    logger.debug("network_sync_unknown_state",
                               node_id=self.node_id,
                               stdout_preview=stdout[:200] if stdout else "empty",
                               note=f"Unknown network state: {current_state}")
                    return False
            else:
                # Failed to get status
                logger.debug("network_sync_status_check_failed",
                           node_id=self.node_id,
                           exit_code=exit_code,
                           stderr=stderr[:200] if stderr else "empty",
                           note="Failed to get network status")
                return False
            
        except Exception as e:
            logger.warning("network_sync_completion_check_failed",
                         node_id=self.node_id,
                         error=str(e))
            return False


class TransactionFinalizationWaiter(BaseWaiter):
    """
    Waits for transaction to be fully processed (in DAG, in ledger).
    
    Combines multiple checks:
    1. Transaction in DAG events
    2. Transaction in ledger (using ledger info, which checks ledger_items directly)
    
    Note: Uses `ledger info` instead of `tx_history` because tx_history depends on
    PVT(a_dag)->datums which may not be populated after snapshot restore.
    
    Usage:
        waiter = TransactionFinalizationWaiter(
            exec_cli_func, node_id, tx_hash, wallet_addr, network, chain
        )
        await waiter.wait(timeout=60.0, name="tx_finalization")
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        tx_hash: str,
        wallet_addr: str,
        network: str = "stagenet",
        chain: str = "zerochain",
        poll_interval: float = 2.0
    ):
        """
        Initialize transaction finalization waiter.
        
        Args:
            exec_cli: CLI execution function
            node_id: Node ID to check
            tx_hash: Transaction hash
            wallet_addr: Wallet address (for UTXO check)
            network: Network name
            chain: Chain name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.tx_hash = tx_hash
        self.wallet_addr = wallet_addr
        self.network = network
        self.chain = chain
        self._dag_checked = False
        self._ledger_checked = False
    
    async def check(self) -> bool:
        """
        Check if transaction is fully finalized.
        
        Returns:
            True if transaction is in DAG and ledger (checked via ledger info)
        """
        try:
            # Step 1: Check if in DAG events (only once)
            if not self._dag_checked:
                exit_code, stdout, stderr = self.exec_cli(
                    self.node_id,
                    f"dag event list -net {self.network} -chain {self.chain} -from events -limit 20",
                    check_output=False
                )
                
                if exit_code == 0 and stdout and self.tx_hash.lower() in stdout.lower():
                    self._dag_checked = True
                    logger.debug("tx_found_in_dag",
                               node_id=self.node_id,
                               tx_hash=self.tx_hash[:16])
                else:
                    return False  # Not in DAG yet
            
            # Step 2: Check if in ledger (only once after DAG check passed)
            if self._dag_checked and not self._ledger_checked:
                # Check via ledger info (checks ledger_items directly, more reliable than tx_history)
                # tx_history depends on PVT(a_dag)->datums which may not be populated after snapshot restore
                exit_code, stdout, stderr = self.exec_cli(
                    self.node_id,
                    f"ledger info -net {self.network} -hash {self.tx_hash}",
                    check_output=False
                )
                
                if exit_code == 0 and stdout:
                    # Check if datum hash is present in output
                    if self.tx_hash.lower() in stdout.lower():
                        # Also check for "Datum_tx_hash" or similar indicators
                        if "Datum_tx_hash" in stdout or "datum" in stdout.lower():
                            self._ledger_checked = True
                            logger.debug("tx_indexed_in_ledger",
                                       node_id=self.node_id,
                                       tx_hash=self.tx_hash[:16],
                                       note="Transaction found in ledger via ledger info")
                            return True
            
            return self._dag_checked and self._ledger_checked
            
        except Exception as e:
            logger.warning("tx_finalization_check_failed",
                         node_id=self.node_id,
                         tx_hash=self.tx_hash[:16],
                         error=str(e))
            return False

