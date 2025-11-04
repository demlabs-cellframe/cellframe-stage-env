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


class UTXOIndexationWaiter(BaseWaiter):
    """
    Waits for UTXO to be indexed in ledger_items (tx_history becomes non-empty).
    
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
            exit_code, stdout, stderr = self.exec_cli(
                self.node_id,
                f"tx_history -addr {self.wallet_addr} -net {self.network} -chain {self.chain}",
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
    1. NET_STATE_ONLINE -> NET_STATE_SYNC_CHAINS (sync starts)
    2. NET_STATE_SYNC_CHAINS -> NET_STATE_ONLINE (sync completes)
    
    During NET_STATE_SYNC_CHAINS, SDK indexes UTXO into ledger_items!
    
    Usage:
        waiter = NetworkSyncCompletionWaiter(exec_cli_func, node_id, network)
        await waiter.wait(timeout=60.0, name="network_sync_completion")
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
                # Check current network state
                if "NET_STATE_SYNC_CHAINS" in stdout:
                    self._sync_started = True
                    logger.debug("network_sync_in_progress",
                               node_id=self.node_id,
                               note="Network is in SYNC_CHAINS state - UTXO indexation in progress")
                    return False
                elif "NET_STATE_ONLINE" in stdout and self._sync_started:
                    logger.debug("network_sync_completed",
                               node_id=self.node_id,
                               note="Network returned to ONLINE after SYNC_CHAINS - UTXO should be indexed")
                    return True
                elif "NET_STATE_ONLINE" in stdout:
                    # Still online, sync hasn't started yet
                    return False
            
            return False
            
        except Exception as e:
            logger.warning("network_sync_completion_check_failed",
                         node_id=self.node_id,
                         error=str(e))
            return False


class TransactionFinalizationWaiter(BaseWaiter):
    """
    Waits for transaction to be fully processed (in DAG, in ledger, UTXO indexed).
    
    Combines multiple checks:
    1. Transaction in DAG events
    2. Transaction in ledger
    3. UTXO indexed in ledger_items (tx_history)
    
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
            True if transaction is in DAG, ledger, and UTXO indexed
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
                # Check via tx_history (also checks UTXO indexation)
                exit_code, stdout, stderr = self.exec_cli(
                    self.node_id,
                    f"tx_history -addr {self.wallet_addr} -net {self.network} -chain {self.chain}",
                    check_output=False
                )
                
                if exit_code == 0 and stdout:
                    if "status: empty" not in stdout.lower():
                        tx_count_match = re.search(r'total_tx_count:\s*(\d+)', stdout, re.IGNORECASE)
                        if tx_count_match and int(tx_count_match.group(1)) > 0:
                            self._ledger_checked = True
                            logger.debug("tx_indexed_in_ledger",
                                       node_id=self.node_id,
                                       tx_hash=self.tx_hash[:16],
                                       tx_count=tx_count_match.group(1))
                            return True
            
            return self._dag_checked and self._ledger_checked
            
        except Exception as e:
            logger.warning("tx_finalization_check_failed",
                         node_id=self.node_id,
                         tx_hash=self.tx_hash[:16],
                         error=str(e))
            return False

