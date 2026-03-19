"""
Waiters for registration operations.

Extracted from genesis_registration.py for better code organization.
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


class NodeListPropagationWaiter(BaseWaiter):
    """
    Wait until all specified nodes have received the node list from GDB.
    
    This is critical to prevent MDBX assertion crashes when nodes try to create
    DB contexts before the node list is available.
    
    CRITICAL: Skips nodes with stopped/crashed containers (they can't receive node list).
    
    Usage:
        waiter = NodeListPropagationWaiter(
            exec_cli_func, docker_client, nodes, expected_count, network_name
        )
        await waiter.wait(timeout=60.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        docker_client,
        nodes: List[NodeConfig],
        expected_count: int,
        network_name: str = "stagenet",
        poll_interval: float = 2.0
    ):
        """
        Initialize node list propagation waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            docker_client: Docker client instance
            nodes: List of nodes to check
            expected_count: Expected number of nodes in the list
            network_name: Network name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.docker_client = docker_client
        self.nodes = nodes
        self.expected_count = expected_count
        self.network_name = network_name
        self._start_time = None
        self._nodes_with_list = 0
        self._running_nodes = 0
    
    async def check(self) -> bool:
        """Check if all running nodes have received the node list."""
        if self._start_time is None:
            self._start_time = time.time()
        
        self._nodes_with_list = 0
        self._running_nodes = 0
        
        for node in self.nodes:
            try:
                # Check if container is running first
                container_name = make_container_name(f"node-{node.node_id}")
                try:
                    container = self.docker_client.containers.get(container_name)
                    container.reload()
                    if container.status != 'running':
                        # Skip stopped/crashed containers
                        logger.debug("skipping_stopped_container",
                                   node_id=node.node_id,
                                   status=container.status)
                        continue
                except Exception:
                    # Container not found or other error - skip it
                    logger.debug("skipping_inaccessible_container",
                               node_id=node.node_id)
                    continue
                
                self._running_nodes += 1
                
                exit_code, stdout, _ = self.exec_cli(
                    node.node_id,
                    f"node list -net {self.network_name}",
                    check_output=False
                )
                
                # Check if node has full list
                if exit_code == 0:
                    # Count "Got N nodes:"
                    match = re.search(r'Got\s+(\d+)\s+nodes', stdout, re.IGNORECASE)
                    if match:
                        node_count = int(match.group(1))
                        if node_count >= self.expected_count:
                            self._nodes_with_list += 1
                            logger.debug("node_has_full_list",
                                       node_id=node.node_id,
                                       count=node_count)
            except Exception as e:
                logger.debug("node_list_check_error",
                           node=node.node_id,
                           error=str(e)[:100])
        
        # If no running nodes, we can't proceed
        if self._running_nodes == 0:
            elapsed = time.time() - self._start_time
            logger.warning("no_running_nodes_to_check",
                         total_nodes=len(self.nodes),
                         elapsed=round(elapsed, 1))
            # Continue waiting - containers might restart
            return False
        
        # All RUNNING nodes have the list?
        if self._nodes_with_list >= self._running_nodes:
            elapsed = time.time() - self._start_time
            logger.info("all_running_nodes_received_node_list",
                       nodes_with_list=self._nodes_with_list,
                       running_nodes=self._running_nodes,
                       total_nodes=len(self.nodes),
                       expected_count=self.expected_count,
                       elapsed=round(elapsed, 1))
            return True
        
        # Log progress
        elapsed = time.time() - self._start_time
        if elapsed > 5.0:  # Only log after 5 seconds
            logger.info("node_list_propagation_progress",
                       ready=self._nodes_with_list,
                       running=self._running_nodes,
                       total=len(self.nodes),
                       missing=self._running_nodes - self._nodes_with_list,
                       elapsed=round(elapsed, 1))
        
        return False
    
    async def wait(self, timeout: float, name: str = "node_list_propagation") -> None:
        """Wait until all running nodes have received the node list."""
        try:
            await super().wait(timeout, name)
        except TimeoutError:
            raise TimeoutError(
                f"Running nodes failed to receive node list after {timeout}s. "
                f"Only {self._nodes_with_list}/{self._running_nodes} running nodes have full list "
                f"(out of {len(self.nodes)} total nodes)."
            )

