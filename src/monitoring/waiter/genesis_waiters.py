"""
Waiters for genesis operations.

Extracted from genesis_esbocs.py for better code organization.
"""

import asyncio
import re
import time
from typing import List, Callable, Optional

from ..base import BaseWaiter
from ...network.models import NodeConfig
from src.utils.logger import get_logger
from src.utils.project import make_container_name

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
            container_name = make_container_name(f"node-{master_node.node_id}")
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

    def notify_matches(self, msg: dict) -> bool:
        msg_hash = (msg.get("hash") or "").lower().replace("0x", "")
        my_hash = self.emission_hash.lower().replace("0x", "")
        return msg_hash == my_hash
    
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

    Supports notify: listens for ``MempoolEvent`` and ``LedgerTxEvent``
    with matching hash.  MempoolEvent fires first (datum enters mempool),
    LedgerTxEvent fires when the transaction is confirmed in the ledger.
    Available in SDK >= 5.8; on older versions falls back to polling.
    
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
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.tx_hash = tx_hash
        self.network_name = network_name
        self.chain = chain
        self._start_time = None

    def notify_matches(self, msg: dict) -> bool:
        msg_hash = (msg.get("hash") or "").lower().replace("0x", "")
        my_hash = self.tx_hash.lower().replace("0x", "")
        return msg_hash == my_hash
    
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

    Supports notify: listens for ``StakeEvent`` (SDK >= 5.8) using
    **hint_only** mode — a ``delegate`` event triggers ``check()``
    across all nodes.  Falls back to polling on SDK <= 5.7.

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
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.nodes = nodes
        self.expected_count = expected_count
        self.network_name = network_name
        self._start_time = None

    def notify_matches(self, msg: dict) -> bool:
        """Match StakeEvent delegate operations for this network."""
        return (msg.get("op") == "delegate"
                and msg.get("net", "") == self.network_name)
    
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

    Supports notify: listens for ``WalletInfo`` and checks balance in payload.
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
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.wallet_name = wallet_name
        self.token_ticker = token_ticker
        self.expected_balance = expected_balance
        self.network_name = network_name
        self._start_time = None

    def notify_matches(self, msg: dict) -> bool:
        wallets = msg.get("wallet", {})
        for wname, wdata in wallets.items():
            if self.wallet_name not in wname:
                continue
            net_data = wdata.get(self.network_name, {})
            for tok in net_data.get("tokens", []):
                if tok.get("ticker") != self.token_ticker:
                    continue
                coins_str = tok.get("coins") or tok.get("datoshi") or "0"
                try:
                    balance = float(str(coins_str).replace(",", ""))
                except (ValueError, TypeError):
                    continue
                if self._check_balance_condition(balance):
                    return True
        return False
    
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
            
            elapsed = time.time() - self._start_time
            condition_str = self.expected_balance or "> 0"

            if exit_code != 0:
                if int(elapsed) % 30 < 2:
                    logger.info("wallet_balance_cli_error",
                               node_id=self.node_id,
                               wallet=self.wallet_name,
                               exit_code=exit_code,
                               stdout_preview=stdout[:300] if stdout else "",
                               stderr_preview=stderr[:300] if stderr else "",
                               elapsed=f"{elapsed:.1f}s")
                return False
            
            import re
            balance_val = None

            # wallet info output varies by SDK version.  Try several patterns:
            #  1) "tVPN: <number>"  — old single-line format
            #  2) token section: "tVPN:\n  ...\n  coins: <number>"
            #  3) any "coins: <number>" (single-token wallets)
            #  4) "datoshi: <number>" (fallback, convert to coins)
            #  5) bare "balance: <number>" (zero-balance format)
            pattern_direct = rf"{re.escape(self.token_ticker)}:\s+([0-9]+(?:\.[0-9]+)?)"
            m = re.search(pattern_direct, stdout)
            if m:
                balance_val = float(m.group(1))

            if balance_val is None:
                # Token section with coins on a separate line
                pattern_section = rf"{re.escape(self.token_ticker)}.*?coins:\s+([0-9]+(?:\.[0-9]+)?)"
                m = re.search(pattern_section, stdout, re.DOTALL)
                if m:
                    balance_val = float(m.group(1))

            if balance_val is None:
                m = re.search(r"coins:\s+([0-9]+(?:\.[0-9]+)?)", stdout)
                if m:
                    balance_val = float(m.group(1))

            if balance_val is None:
                m = re.search(r"datoshi:\s+([0-9]+)", stdout)
                if m:
                    balance_val = int(m.group(1)) / 1e18

            if balance_val is None:
                m = re.search(r"\bbalance:\s+([0-9]+(?:\.[0-9]+)?)", stdout)
                if m:
                    balance_val = float(m.group(1))

            if balance_val is not None:
                if self._check_balance_condition(balance_val):
                    logger.info("wallet_balance_condition_met",
                               node_id=self.node_id,
                               wallet=self.wallet_name,
                               token=self.token_ticker,
                               balance=str(balance_val),
                               condition=condition_str,
                               elapsed=f"{elapsed:.1f}s")
                    return True
            
            if int(elapsed) % 30 < 2:
                logger.info("wallet_balance_waiting",
                           node_id=self.node_id,
                           wallet=self.wallet_name,
                           token=self.token_ticker,
                           condition=condition_str,
                           stdout_preview=stdout[:500] if stdout else "<empty>",
                           elapsed=f"{elapsed:.1f}s")
            
        except Exception as e:
            logger.info("wallet_balance_check_error",
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
        self._notify_block_count = 0

    def notify_matches(self, msg: dict) -> bool:
        if msg.get("chain") != self.chain or msg.get("net") != self.network_name:
            return False
        self._notify_block_count += 1
        return self._notify_block_count >= self.min_blocks
    
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
    Wait for Global DB synchronization across multiple nodes.

    Two modes of operation:

    1. Default (no group): checks 'node list' output — lightweight GDB readiness check.
    2. Group mode (group specified): checks 'global_db get_keys -group <group>' — waits
       until a specific GDB group is replicated to all target nodes. Optionally checks
       for a specific key within the group.

    Supports notify: listens for ``GDBEvent`` (SDK >= 5.8) using **hint_only**
    mode — a notification triggers an immediate ``check()`` across all nodes
    rather than completing the waiter directly.  Falls back to pure polling
    on SDK <= 5.7.

    Usage:
        # Node list sync (default)
        waiter = GlobalDBNodeListSyncWaiter(exec_cli, nodes=[node1, node2], network_name="stagenet")
        await waiter.wait(timeout=60.0)

        # Group sync — wait until group has data on all nodes
        waiter = GlobalDBNodeListSyncWaiter(exec_cli, nodes=[node1, node2],
                                            group="cdb.stagenet.serials")
        await waiter.wait(timeout=60.0)

        # Group + key — wait for specific key in group on all nodes
        waiter = GlobalDBNodeListSyncWaiter(exec_cli, nodes=[node1, node2],
                                            group="cdb.stagenet.serials", key="ABCD-1234-EFGH-5678")
        await waiter.wait(timeout=60.0)
    """

    def __init__(
        self,
        exec_cli: Callable,
        node: Optional[NodeConfig] = None,
        nodes: Optional[List[NodeConfig]] = None,
        network_name: str = "stagenet",
        poll_interval: float = 2.0,
        min_output_length: int = 50,
        group: Optional[str] = None,
        key: Optional[str] = None
    ):
        super().__init__(poll_interval)
        self.exec_cli = exec_cli

        if nodes:
            self.nodes = nodes if isinstance(nodes, list) else [nodes]
        elif node:
            self.nodes = [node]
        else:
            raise ValueError("Either 'node' or 'nodes' must be provided")

        self.network_name = network_name
        self.min_output_length = min_output_length
        self.group = group
        self.key = key
        self._start_time = None
        self._check_count = 0
        self._synced_nodes = set()

    def notify_matches(self, msg: dict) -> bool:
        """Match GDBEvent for the relevant group (or any node-list event)."""
        msg_group = msg.get("group", "")
        if self.group:
            if self.group not in msg_group:
                return False
            if self.key:
                return msg.get("key", "") == self.key
            return True
        return "node" in msg_group.lower()
    
    def _build_check_command(self) -> str:
        """Build CLI command depending on mode."""
        if self.group:
            return f"global_db get_keys -group {self.group}"
        return f"node list -net {self.network_name}"
    
    def _is_synced(self, output: str) -> bool:
        """Evaluate whether output indicates the node is synced."""
        if self.group:
            if "No data" in output or "error" in output.lower():
                return False
            if self.key:
                return self.key in output
            return True
        # Default node-list mode
        return "No records" not in output and len(output) >= self.min_output_length
    
    async def check(self) -> bool:
        """Check if Global DB is synced on ALL nodes."""
        if self._start_time is None:
            self._start_time = time.time()
            mode = "group" if self.group else "node_list"
            extra = f" group={self.group}" if self.group else ""
            if self.key:
                extra += f" key={self.key}"
            logger.info("global_db_sync_started",
                       mode=mode, nodes=[n.node_id for n in self.nodes],
                       network=self.network_name, **({} if not extra else {"detail": extra.strip()}))
        
        self._check_count += 1
        
        nodes_to_check = [n for n in self.nodes if n.node_id not in self._synced_nodes]
        if not nodes_to_check:
            return True
        
        cmd = self._build_check_command()
        
        for node in nodes_to_check:
            try:
                exit_code, stdout, stderr = self.exec_cli(
                    node.node_id, cmd, check_output=False
                )
                
                if exit_code != 0:
                    logger.debug("global_db_sync_check",
                               status="command_failed",
                               node_id=node.node_id,
                               check_count=self._check_count,
                               exit_code=exit_code)
                    continue
                
                output = (stdout or '').strip()
                
                if not self._is_synced(output):
                    if self._check_count % 5 == 0:
                        logger.debug("global_db_not_synced_yet",
                                   node_id=node.node_id,
                                   check_count=self._check_count,
                                   group=self.group,
                                   key=self.key)
                    continue
                
                self._synced_nodes.add(node.node_id)
                elapsed = time.time() - self._start_time
                logger.info("global_db_synced",
                           node_id=node.node_id,
                           network=self.network_name,
                           group=self.group,
                           check_count=self._check_count,
                           synced_count=len(self._synced_nodes),
                           total_nodes=len(self.nodes),
                           elapsed=f"{elapsed:.1f}s")
                
            except Exception as e:
                logger.debug("global_db_sync_check_error",
                           node_id=node.node_id,
                           check_count=self._check_count,
                           error=str(e))
        
        all_synced = len(self._synced_nodes) == len(self.nodes)
        if all_synced:
            elapsed = time.time() - self._start_time
            logger.info("global_db_all_nodes_synced",
                       node_ids=[n.node_id for n in self.nodes],
                       network=self.network_name,
                       group=self.group,
                       total_nodes=len(self.nodes),
                       elapsed=f"{elapsed:.1f}s")
        return all_synced

