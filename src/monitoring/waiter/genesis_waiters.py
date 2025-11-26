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
    Wait for CLI server to be ready on node.
    
    Usage:
        waiter = CLIReadyWaiter(exec_cli_func, node_id, network_name)
        await waiter.wait(timeout=30.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        network_name: str = "stagenet",
        poll_interval: float = 0.5
    ):
        """
        Initialize CLI ready waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node_id: Node ID to check
            network_name: Network name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.network_name = network_name
        self._start_time = None
    
    async def check(self) -> bool:
        """Check if CLI is ready."""
        if self._start_time is None:
            self._start_time = time.time()
        
        try:
            exit_code, stdout, stderr = self.exec_cli(
                self.node_id,
                f"net -net {self.network_name} get status",
                check_output=False
            )
            if exit_code == 0:
                elapsed = time.time() - self._start_time
                logger.debug("cli_ready",
                           node_id=self.node_id,
                           elapsed=f"{elapsed:.1f}s")
                return True
        except Exception:
            pass
        
        return False

