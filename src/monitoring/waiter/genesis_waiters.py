"""
Waiters for genesis operations.

Extracted from genesis_esbocs.py for better code organization.
"""

import asyncio
import time
from typing import List, Callable, Optional

from ..base import BaseWaiter
from ...network.models import NodeConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MasterContainersRunningWaiter(BaseWaiter):
    """
    Wait for master node containers to be running.
    
    Usage:
        waiter = MasterContainersRunningWaiter(docker_client, master_nodes)
        await waiter.wait(timeout=60.0)
    """
    
    def __init__(
        self,
        docker_client,
        master_nodes: List[NodeConfig],
        poll_interval: float = 1.0
    ):
        """
        Initialize master containers waiter.
        
        Args:
            docker_client: Docker client instance
            master_nodes: List of master nodes
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.docker_client = docker_client
        self.master_nodes = master_nodes
    
    async def check(self) -> bool:
        """Check if all master containers are running."""
        for master_node in self.master_nodes:
            container_name = f"cellframe-stage-node-{master_node.node_id}"
            try:
                container = self.docker_client.containers.get(container_name)
                container.reload()
                if container.status != 'running':
                    return False
            except Exception:
                return False
        return True


class EmissionInLedgerWaiter(BaseWaiter):
    """
    Wait for emission to appear in ledger (NOT just mempool).
    
    CRITICAL: Emission must be in ledger (processed by DAG-PoA) before it can be used.
    Emission in mempool is not enough - SDK requires it to be in ledger.
    
    Usage:
        waiter = EmissionInLedgerWaiter(exec_cli_func, node_id, emission_hash, network_name, chain)
        await waiter.wait(timeout=60.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        emission_hash: str,
        network_name: str = "stagenet",
        chain: str = "zerochain",
        poll_interval: float = 2.0
    ):
        """
        Initialize emission in ledger waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node_id: Node ID to check
            emission_hash: Emission hash to look for
            network_name: Network name
            chain: Chain name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.emission_hash = emission_hash
        self.network_name = network_name
        self.chain = chain
        self._start_time = None
    
    async def check(self) -> bool:
        """Check if emission is in ledger."""
        if self._start_time is None:
            self._start_time = time.time()
        
        # Check ledger (emission must be processed by DAG-PoA)
        exit_code, stdout, stderr = self.exec_cli(
            self.node_id,
            f"ledger list coins -net {self.network_name} -chain {self.chain}",
            check_output=False
        )
        if exit_code == 0 and stdout:
            emission_found = self.emission_hash.lower() in stdout.lower()
            if emission_found:
                elapsed = time.time() - self._start_time
                logger.info("emission_found_in_ledger",
                           node_id=self.node_id,
                           emission=self.emission_hash[:16],
                           elapsed=f"{elapsed:.1f}s",
                           method="ledger")
                return True
        
        # Diagnostic: Check mempool status (for debugging)
        exit_code, stdout, stderr = self.exec_cli(
            self.node_id,
            f"mempool list -net {self.network_name} -chain {self.chain}",
            check_output=False
        )
        if exit_code == 0 and stdout:
            emission_in_mempool = self.emission_hash.lower() in stdout.lower()
            if emission_in_mempool and time.time() - self._start_time > 10:
                # Log warning if emission still in mempool after 10s
                logger.debug("emission_still_in_mempool",
                           node_id=self.node_id,
                           emission=self.emission_hash[:16],
                           elapsed=f"{time.time() - self._start_time:.1f}s",
                           note="Emission in mempool but not in ledger - may need DAG processing")
        
        return False


class TransactionProcessedWaiter(BaseWaiter):
    """
    Wait for transaction to be processed (appear in ledger or mempool).
    
    Usage:
        waiter = TransactionProcessedWaiter(exec_cli_func, node_id, tx_hash, network_name, chain)
        await waiter.wait(timeout=30.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        tx_hash: str,
        network_name: str = "stagenet",
        chain: str = "zerochain",
        poll_interval: float = 1.0
    ):
        """
        Initialize transaction processed waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node_id: Node ID to check
            tx_hash: Transaction hash to look for
            network_name: Network name
            chain: Chain name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.tx_hash = tx_hash
        self.network_name = network_name
        self.chain = chain
        self._start_time = None
    
    async def check(self) -> bool:
        """Check if transaction is processed."""
        if self._start_time is None:
            self._start_time = time.time()
        
        # Check ledger first
        exit_code, stdout, stderr = self.exec_cli(
            self.node_id,
            f"ledger list coins -net {self.network_name} -chain {self.chain}",
            check_output=False
        )
        if exit_code == 0 and stdout:
            tx_found = self.tx_hash.lower() in stdout.lower()
            if tx_found:
                elapsed = time.time() - self._start_time
                logger.info("transaction_found_in_ledger",
                           node_id=self.node_id,
                           tx_hash=self.tx_hash[:16],
                           elapsed=f"{elapsed:.1f}s")
                return True
        
        # Check mempool as fallback
        exit_code, stdout, stderr = self.exec_cli(
            self.node_id,
            f"mempool list -net {self.network_name} -chain {self.chain}",
            check_output=False
        )
        if exit_code == 0 and stdout:
            tx_found = self.tx_hash.lower() in stdout.lower()
            if tx_found:
                elapsed = time.time() - self._start_time
                logger.info("transaction_found_in_mempool",
                           node_id=self.node_id,
                           tx_hash=self.tx_hash[:16],
                           elapsed=f"{elapsed:.1f}s")
                return True
        
        return False


class GDBSyncCompleteWaiter(BaseWaiter):
    """
    Wait for GDB sync to complete across nodes.
    
    Usage:
        waiter = GDBSyncCompleteWaiter(exec_cli_func, nodes, network_name)
        await waiter.wait(timeout=30.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        nodes: List[NodeConfig],
        network_name: str = "stagenet",
        poll_interval: float = 2.0
    ):
        """
        Initialize GDB sync complete waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            nodes: List of nodes to check
            network_name: Network name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.nodes = nodes
        self.network_name = network_name
        self._start_time = None
    
    async def check(self) -> bool:
        """Check if GDB sync is complete."""
        if self._start_time is None:
            self._start_time = time.time()
        
        # Check GDB sync status on all nodes
        for node in self.nodes:
            try:
                exit_code, stdout, stderr = self.exec_cli(
                    node.node_id,
                    f"global_db status -net {self.network_name}",
                    check_output=False
                )
                if exit_code != 0:
                    return False
            except Exception:
                return False
        
        elapsed = time.time() - self._start_time
        logger.info("gdb_sync_complete",
                   node_count=len(self.nodes),
                   elapsed=f"{elapsed:.1f}s")
        return True


class DelegationsSyncedWaiter(BaseWaiter):
    """
    Wait for delegations to be synced across nodes.
    
    Usage:
        waiter = DelegationsSyncedWaiter(exec_cli_func, nodes, expected_count, network_name)
        await waiter.wait(timeout=60.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        nodes: List[NodeConfig],
        expected_count: int,
        network_name: str = "stagenet",
        poll_interval: float = 2.0
    ):
        """
        Initialize delegations synced waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            nodes: List of nodes to check
            expected_count: Expected number of delegations
            network_name: Network name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.nodes = nodes
        self.expected_count = expected_count
        self.network_name = network_name
        self._start_time = None
    
    async def check(self) -> bool:
        """Check if delegations are synced."""
        if self._start_time is None:
            self._start_time = time.time()
        
        for node in self.nodes:
            try:
                exit_code, stdout, stderr = self.exec_cli(
                    node.node_id,
                    f"srv_stake list keys -net {self.network_name}",
                    check_output=False
                )
                if exit_code != 0:
                    return False
                
                # Check if we have expected number of delegations
                if stdout:
                    # Count keys in output (rough estimate)
                    key_count = stdout.count('addr:') or stdout.count('address:')
                    if key_count < self.expected_count:
                        return False
            except Exception:
                return False
        
        elapsed = time.time() - self._start_time
        logger.info("delegations_synced_across_nodes",
                   node_count=len(self.nodes),
                   expected_count=self.expected_count,
                   elapsed=f"{elapsed:.1f}s")
        return True


class CLIReadyWaiter(BaseWaiter):
    """
    Wait for CLI server to be ready on nodes.
    
    Usage:
        waiter = CLIReadyWaiter(exec_cli_func, nodes, network_name)
        await waiter.wait(timeout=30.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        nodes: List[NodeConfig],
        network_name: str = "stagenet",
        poll_interval: float = 0.5
    ):
        """
        Initialize CLI ready waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            nodes: List of nodes to check
            network_name: Network name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.nodes = nodes
        self.network_name = network_name
        self._start_time = None
    
    async def check(self) -> bool:
        """Check if CLI is ready on all nodes."""
        if self._start_time is None:
            self._start_time = time.time()
        
        all_ready = True
        for node in self.nodes:
            try:
                exit_code, stdout, stderr = self.exec_cli(
                    node.node_id,
                    f"net -net {self.network_name} get status",
                    check_output=False
                )
                if exit_code != 0:
                    all_ready = False
                    break
            except Exception:
                all_ready = False
                break
        
        if all_ready:
            elapsed = time.time() - self._start_time
            logger.debug("cli_ready_all_nodes",
                       node_count=len(self.nodes),
                       elapsed=f"{elapsed:.1f}s")
            return True
            
        return False


class WalletBalanceWaiter(BaseWaiter):
    """
    Wait for wallet to have specified balance of token.
    
    Supports flexible balance conditions:
    - Simple value: expected_balance="1000000" (exact match)
    - Comparison: expected_balance="> 100", ">= 1e+18", "< 500"
    - Python expression: expected_balance="balance > (1000 + 13.4)"
    - None: checks for any non-zero balance
    
    Usage:
        waiter = WalletBalanceWaiter(exec_cli_func, node_id, wallet_name, token_ticker, expected_balance="> 1e+18")
        await waiter.wait(timeout=60.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        wallet_name: str,
        token_ticker: str = "TCELL",
        expected_balance: Optional[str] = None,
        network_name: str = "stagenet",
        poll_interval: float = 2.0
    ):
        """
        Initialize wallet balance waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node_id: Node ID to check
            wallet_name: Wallet name to check balance for
            token_ticker: Token ticker to check (e.g., "TCELL")
            expected_balance: Balance condition (e.g., "> 1000", "1e+18", "balance >= 100")
                            If None, checks for any non-zero balance
            network_name: Network name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.wallet_name = wallet_name
        self.token_ticker = token_ticker
        self.expected_balance = expected_balance
        self.network_name = network_name
        self._start_time = None
    
    def _check_balance_condition(self, balance: float) -> bool:
        """
        Check if balance meets the expected condition.
        
        Args:
            balance: Actual balance value
            
        Returns:
            True if condition is met
        """
        if self.expected_balance is None:
            # No condition specified - just check for non-zero
            return balance > 0
        
        condition = self.expected_balance.strip()
        
        # Try to parse as comparison operator
        import re
        comparison_match = re.match(r'^([<>=!]+)\s*(.+)$', condition)
        
        if comparison_match:
            operator = comparison_match.group(1)
            value_str = comparison_match.group(2).strip()
            
            try:
                expected_value = float(value_str)
                
                if operator == '>':
                    return balance > expected_value
                elif operator == '>=':
                    return balance >= expected_value
                elif operator == '<':
                    return balance < expected_value
                elif operator == '<=':
                    return balance <= expected_value
                elif operator == '==' or operator == '=':
                    return abs(balance - expected_value) < 1e-10  # Float comparison with epsilon
                elif operator == '!=':
                    return abs(balance - expected_value) >= 1e-10
                else:
                    logger.warning(f"Unknown operator: {operator}, checking for non-zero balance")
                    return balance > 0
            except ValueError:
                logger.warning(f"Cannot parse expected value: {value_str}")
                return balance > 0
        
        # Try to evaluate as Python expression
        if 'balance' in condition:
            try:
                # Safe evaluation with balance variable
                result = eval(condition, {"__builtins__": {}}, {"balance": balance})
                return bool(result)
            except Exception as e:
                logger.warning(f"Cannot evaluate expression '{condition}': {e}")
                return balance > 0
        
        # Try to parse as exact value
        try:
            expected_value = float(condition)
            return abs(balance - expected_value) < 1e-10
        except ValueError:
            logger.warning(f"Cannot parse balance condition: {condition}, checking for non-zero")
            return balance > 0
    
    async def check(self) -> bool:
        """Check if wallet has expected balance of the token."""
        if self._start_time is None:
            self._start_time = time.time()
        
        try:
            exit_code, stdout, stderr = self.exec_cli(
                self.node_id,
                f"wallet info -w {self.wallet_name} -net {self.network_name}",
                check_output=False
            )
            
            if exit_code != 0:
                return False
            
            # Check if token ticker appears in output with balance
            # Looking for patterns like "TCELL: 1000000.0" or "TCELL:     12345.67"
            import re
            pattern = rf"{re.escape(self.token_ticker)}:\s+([0-9]+(?:\.[0-9]+)?)"
            match = re.search(pattern, stdout)
            
            if match:
                balance_str = match.group(1)
                try:
                    balance = float(balance_str)
                    
                    # Check if balance meets condition
                    if self._check_balance_condition(balance):
                        elapsed = time.time() - self._start_time
                        condition_str = self.expected_balance or "> 0"
                        logger.info("wallet_balance_condition_met",
                                   node_id=self.node_id,
                                   wallet=self.wallet_name,
                                   token=self.token_ticker,
                                   balance=balance_str,
                                   condition=condition_str,
                                   elapsed=f"{elapsed:.1f}s")
                        return True
                except ValueError:
                    pass
            
            # Log progress periodically (every 10s)
            elapsed = time.time() - self._start_time
            if int(elapsed) % 10 == 0 and elapsed > 0:
                condition_str = self.expected_balance or "> 0"
                logger.debug("waiting_for_wallet_balance",
                           node_id=self.node_id,
                           wallet=self.wallet_name,
                           token=self.token_ticker,
                           condition=condition_str,
                           elapsed=f"{elapsed:.1f}s")
            
        except Exception as e:
            logger.debug("wallet_balance_check_error",
                       node_id=self.node_id,
                       wallet=self.wallet_name,
                       error=str(e))
        
        return False


class BlockCreatedWaiter(BaseWaiter):
    """
    Wait for block(s) to be created on a chain.
    
    Monitors 'block list' command output to detect when blocks have been created
    on the specified chain. This is critical for ESBocs consensus where block
    creation takes time and requires validators.
    
    Usage:
        waiter = BlockCreatedWaiter(exec_cli_func, node_config, chain_name, network_name, min_blocks)
        await waiter.wait(timeout=180.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node: NodeConfig,
        chain: str,
        network_name: str = "stagenet",
        min_blocks: int = 1,
        poll_interval: float = 3.0
    ):
        """
        Initialize block created waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node: Node to check blocks on
            chain: Chain name (e.g., "main", "zerochain")
            network_name: Network name
            min_blocks: Minimum number of blocks required (default: 1)
            poll_interval: Seconds between checks (default: 3.0s - ESBocs is slow)
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node = node
        self.chain = chain
        self.network_name = network_name
        self.min_blocks = min_blocks
        self._start_time = None
        self._check_count = 0
    
    async def check(self) -> bool:
        """Check if block(s) have been created on the chain."""
        if self._start_time is None:
            self._start_time = time.time()
        
        self._check_count += 1
        
        try:
            # Execute 'block list' to check for blocks
            exit_code, stdout, stderr = self.exec_cli(
                self.node.node_id,
                f"block list -chain {self.chain} -net {self.network_name}",
                check_output=False
            )
            
            if exit_code != 0:
                logger.debug("block_created_check",
                           status="command_failed",
                           node_id=self.node.node_id,
                           chain=self.chain,
                           check_count=self._check_count,
                           exit_code=exit_code)
                return False
            
            output = (stdout or '').strip()
            
            # Parse block count from "have blocks: N"
            import re
            match = re.search(r'have blocks:\s*(\d+)', output, re.IGNORECASE)
            
            if match:
                block_count = int(match.group(1))
                
                if block_count >= self.min_blocks:
                    elapsed = time.time() - self._start_time
                    logger.info("blocks_created",
                               node_id=self.node.node_id,
                               chain=self.chain,
                               network=self.network_name,
                               block_count=block_count,
                               min_blocks=self.min_blocks,
                               check_count=self._check_count,
                               elapsed=f"{elapsed:.1f}s")
                    return True
                else:
                    # Log progress every 10 checks (30s with 3s interval)
                    if self._check_count % 10 == 0:
                        elapsed = time.time() - self._start_time
                        logger.info("waiting_for_block_creation",
                                   node_id=self.node.node_id,
                                   chain=self.chain,
                                   current_blocks=block_count,
                                   min_blocks=self.min_blocks,
                                   check_count=self._check_count,
                                   elapsed=f"{elapsed:.1f}s")
                    return False
            else:
                # Pattern not found - log for debugging
                if self._check_count % 10 == 0:
                    logger.debug("block_count_pattern_not_found",
                               node_id=self.node.node_id,
                               chain=self.chain,
                               check_count=self._check_count,
                               output_preview=output[:100])
                return False
            
        except Exception as e:
            logger.debug("block_created_check_error",
                       node_id=self.node.node_id,
                       chain=self.chain,
                       check_count=self._check_count,
                       error=str(e))
            return False


class GlobalDBNodeListSyncWaiter(BaseWaiter):
    """
    Wait for Global DB synchronization by checking node list.
    
    Monitors 'node list' command output to detect when Global DB has synchronized
    records across the network. This is a lightweight check that indicates GDB
    is ready for operations.
    
    Usage:
        waiter = GlobalDBNodeListSyncWaiter(exec_cli_func, node_config, network_name)
        await waiter.wait(timeout=60.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node: NodeConfig,
        network_name: str = "stagenet",
        poll_interval: float = 2.0,
        min_output_length: int = 50
    ):
        """
        Initialize Global DB node list sync waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node: Node to check
            network_name: Network name
            poll_interval: Seconds between checks (default: 2.0s)
            min_output_length: Minimum output length to consider synced (default: 50 chars)
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node = node
        self.network_name = network_name
        self.min_output_length = min_output_length
        self._start_time = None
        self._check_count = 0
    
    async def check(self) -> bool:
        """Check if Global DB is synced by verifying node list has records."""
        if self._start_time is None:
            self._start_time = time.time()
        
        self._check_count += 1
        
        try:
            # Execute 'node list' to check Global DB sync status
            exit_code, stdout, stderr = self.exec_cli(
                self.node.node_id,
                f"node list -net {self.network_name}",
                check_output=False
            )
            
            if exit_code != 0:
                logger.debug("global_db_node_list_sync_check",
                           status="command_failed",
                           node_id=self.node.node_id,
                           check_count=self._check_count,
                           exit_code=exit_code)
                return False
            
            output = (stdout or '').strip()
            
            # Check if Global DB has records
            # "No records" indicates GDB is not synced yet
            # Valid output with nodes indicates GDB is synced
            if "No records" in output or len(output) < self.min_output_length:
                logger.debug("global_db_not_synced_yet",
                           node_id=self.node.node_id,
                           check_count=self._check_count,
                           output_length=len(output),
                           has_no_records="No records" in output)
                return False
            
            # Global DB is synced
            elapsed = time.time() - self._start_time
            logger.info("global_db_synced",
                       node_id=self.node.node_id,
                       network=self.network_name,
                       check_count=self._check_count,
                       elapsed=f"{elapsed:.1f}s")
            return True
            
        except Exception as e:
            logger.debug("global_db_sync_check_error",
                       node_id=self.node.node_id,
                       check_count=self._check_count,
                       error=str(e))
            return False

