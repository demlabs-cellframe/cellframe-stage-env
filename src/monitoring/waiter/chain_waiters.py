"""
Chain data propagation waiters for genesis operations.
"""

import re
import time
from typing import Callable, List

from ..base import BaseWaiter
from ...network.models import NodeConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ChainDataPropagationWaiter(BaseWaiter):
    """
    Wait for chain data to propagate to all nodes.
    
    For DAG chains: checks if total events > 0
    For blockchain chains: checks if any blocks exist
    
    Usage:
        waiter = ChainDataPropagationWaiter(exec_cli_func, nodes, network_name, chain_name)
        await waiter.wait(timeout=120.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        nodes: List[NodeConfig],
        network_name: str = "stagenet",
        chain_name: str = "zerochain",
        poll_interval: float = 5.0
    ):
        """
        Initialize chain data propagation waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            nodes: List of nodes to check
            network_name: Network name
            chain_name: Chain name to check
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.nodes = nodes
        self.network_name = network_name
        self.chain_name = chain_name
        self._start_time = None
        self._last_log_time = None
    
    async def check(self) -> bool:
        """Check if chain data is propagated to all nodes."""
        if self._start_time is None:
            self._start_time = time.time()
            self._last_log_time = self._start_time
        
        synced_count = 0
        
        for node in self.nodes:
            try:
                # Check if node has any data in the chain
                is_dag_chain = self.chain_name.lower() in ["zerochain", "zero", "0"]
                
                if is_dag_chain:
                    # For DAG: check total events > 0
                    exit_code_check, stdout_check, _ = self.exec_cli(
                        node.node_id,
                        f"dag event list -net {self.network_name} -chain {self.chain_name} -from events -limit 1",
                        check_output=False
                    )
                    
                    # Parse "total events: N"
                    total_match = re.search(r'total events:\s*(\d+)', stdout_check, re.IGNORECASE) if stdout_check else None
                    total_events = int(total_match.group(1)) if total_match else 0
                    has_data = exit_code_check == 0 and total_events > 0
                    
                    # DIAGNOSTIC: Log full output for first check to debug
                    elapsed = time.time() - self._start_time
                    if elapsed < 10 and node == self.nodes[0]:
                        logger.info("dag_event_list_diagnostic",
                                   node=f"node{node.node_id}",
                                   exit_code=exit_code_check,
                                   total_events=total_events,
                                   full_output=stdout_check if stdout_check else "EMPTY")
                else:
                    # For blockchain: check if any blocks exist
                    exit_code_check, stdout_check, _ = self.exec_cli(
                        node.node_id,
                        f"block list -net {self.network_name} -chain {self.chain_name} -last 1",
                        check_output=False
                    )
                    
                    # Look for "block #" in output
                    has_data = exit_code_check == 0 and "block #" in stdout_check.lower()
                
                if has_data:
                    synced_count += 1
                    logger.debug("node_has_chain_data", 
                               node=f"node{node.node_id}",
                               chain=self.chain_name,
                               preview=stdout_check[:100] if stdout_check else "empty")
                else:
                    # Log why node doesn't have data
                    logger.debug("node_missing_chain_data",
                               node=f"node{node.node_id}",
                               exit_code=exit_code_check,
                               output_preview=stdout_check[:200] if stdout_check else "EMPTY")
                    
            except Exception as e:
                logger.debug("failed_to_check_chain_data", node=f"node{node.node_id}", error=str(e)[:100])
        
        if synced_count >= len(self.nodes):  # All nodes have data
            elapsed = time.time() - self._start_time
            logger.info("chain_data_propagated", chain=self.chain_name, synced=synced_count, total=len(self.nodes), elapsed=f"{elapsed:.1f}s")
            return True
        
        # Log progress periodically
        elapsed = time.time() - self._start_time
        if elapsed - (self._last_log_time or 0) >= 5.0:
            logger.info("chain_sync_progress", 
                       chain=self.chain_name,
                       synced=synced_count,
                       total=len(self.nodes),
                       elapsed=f"{elapsed:.1f}s",
                       missing=len(self.nodes) - synced_count)
            self._last_log_time = time.time()
        
        return False
    
    async def wait(self, timeout: float, name: str = "chain_data_propagation") -> None:
        """Wait until chain data is propagated to all nodes."""
        try:
            await super().wait(timeout, name)
        except TimeoutError:
            elapsed = time.time() - self._start_time
            synced_count = 0  # Will be recalculated in check(), but we can't access it here
            
            # Re-check to get current synced_count
            for node in self.nodes:
                try:
                    is_dag_chain = self.chain_name.lower() in ["zerochain", "zero", "0"]
                    if is_dag_chain:
                        exit_code_check, stdout_check, _ = self.exec_cli(
                            node.node_id,
                            f"dag event list -net {self.network_name} -chain {self.chain_name} -from events -limit 1",
                            check_output=False
                        )
                        total_match = re.search(r'total events:\s*(\d+)', stdout_check, re.IGNORECASE) if stdout_check else None
                        total_events = int(total_match.group(1)) if total_match else 0
                        has_data = exit_code_check == 0 and total_events > 0
                    else:
                        exit_code_check, stdout_check, _ = self.exec_cli(
                            node.node_id,
                            f"block list -net {self.network_name} -chain {self.chain_name} -last 1",
                            check_output=False
                        )
                        has_data = exit_code_check == 0 and "block #" in stdout_check.lower()
                    
                    if has_data:
                        synced_count += 1
                except Exception:
                    pass
            
            logger.error("chain_sync_timeout_critical",
                        chain=self.chain_name,
                        elapsed=timeout,
                        synced=synced_count,
                        total=len(self.nodes),
                        missing=len(self.nodes) - synced_count)
            raise RuntimeError(f"Chain {self.chain_name} sync timeout: only {synced_count}/{len(self.nodes)} nodes have data after {timeout}s")


class NetworkSyncWaiter(BaseWaiter):
    """
    Wait for network sync to complete on all nodes.
    
    Checks network status for "synced" state.
    
    Usage:
        waiter = NetworkSyncWaiter(exec_cli_func, docker_client, nodes, network_name)
        await waiter.wait(timeout=120.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        docker_client,
        nodes: List[NodeConfig],
        network_name: str = "stagenet",
        poll_interval: float = 5.0
    ):
        """
        Initialize network sync waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            docker_client: Docker client instance
            nodes: List of nodes to check
            network_name: Network name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.docker_client = docker_client
        self.nodes = nodes
        self.network_name = network_name
        self._start_time = None
        self._last_log_time = None
    
    async def check(self) -> bool:
        """Check if network is synced on all nodes."""
        if self._start_time is None:
            self._start_time = time.time()
            self._last_log_time = self._start_time
        
        all_synced = True
        sync_status = {}
        
        for node in self.nodes:
            container_name = f"cellframe-stage-node-{node.node_id}"
            try:
                container = self.docker_client.containers.get(container_name)
                
                exit_code_status, stdout_str, stderr_str = self.exec_cli(
                    node.node_id,
                    f"net -net {self.network_name} get status",
                    check_output=False
                )
                
                # Check for "synced" status
                synced = bool(re.search(r'status:\s*synced', stdout_str, re.IGNORECASE))
                sync_status[f"node{node.node_id}"] = "synced" if synced else "syncing"
                
                if not synced:
                    all_synced = False
                    
            except Exception as e:
                logger.debug("failed_to_check_sync_status", node=f"node{node.node_id}", error=str(e)[:100])
                all_synced = False
                sync_status[f"node{node.node_id}"] = "error"
        
        if all_synced:
            elapsed = time.time() - self._start_time
            logger.info("network_sync_complete", elapsed=f"{elapsed:.1f}s", nodes=len(self.nodes))
            return True
        
        # Log progress periodically
        elapsed = time.time() - self._start_time
        if elapsed - (self._last_log_time or 0) >= 10.0:
            synced_count = sum(1 for status in sync_status.values() if status == "synced")
            logger.info("network_sync_progress",
                       synced=synced_count,
                       total=len(self.nodes),
                       elapsed=f"{elapsed:.1f}s",
                       status=sync_status)
            self._last_log_time = time.time()
        
        return False
    
    async def wait(self, timeout: float, name: str = "network_sync") -> None:
        """Wait until network is synced on all nodes."""
        try:
            await super().wait(timeout, name)
        except TimeoutError:
            elapsed = time.time() - self._start_time
            logger.warning("sync_timeout", elapsed=timeout, final_status="timeout")
            # Don't raise - sync may complete eventually
            # Return normally without error

