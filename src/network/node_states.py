"""
Node state management and verification for Cellframe stagenet.

Provides intelligent waiting for node state transitions:
- Online/Offline state verification
- Phased startup coordination (ROOT → MASTER → FULL)
- State polling with configurable timeouts
"""

import asyncio
import json
from typing import List, Set
from enum import Enum

import docker

from src.utils.logger import get_logger
from .models import NodeConfig


logger = get_logger(__name__)


class NodeState(Enum):
    """Node operational states."""
    OFFLINE = "NET_STATE_OFFLINE"
    ONLINE = "NET_STATE_ONLINE"
    LINKS_PREPARE = "NET_STATE_LINKS_PREPARE"
    LINKS_CONNECTING = "NET_STATE_LINKS_CONNECTING"
    LINKS_ESTABLISHED = "NET_STATE_LINKS_ESTABLISHED"
    ADDR_REQUEST = "NET_STATE_ADDR_REQUEST"
    UNKNOWN = "UNKNOWN"


class NodeStateManager:
    """
    Manages node state verification and phased startup coordination.
    
    Key responsibilities:
    - Wait for nodes to reach specific states (online/offline)
    - Coordinate phased startup (ROOT → MASTER → FULL)
    - Poll node states with intelligent retry logic
    """
    
    def __init__(
        self,
        docker_client: docker.DockerClient,
        project_name: str = "cellframe-stage",
        cli_path: str = "cellframe-node-cli",
        network_name: str = "stagenet"
    ):
        """
        Initialize node state manager.
        
        Args:
            docker_client: Docker client instance
            project_name: Docker Compose project name
            cli_path: Path to cellframe-node-cli
            network_name: Network name for CLI commands
        """
        self.docker_client = docker_client
        self.project_name = project_name
        self.cli_path = cli_path
        self.network_name = network_name
    
    async def wait_for_nodes_online(
        self,
        nodes: List[NodeConfig],
        timeout: float = 60.0,
        poll_interval: float = 2.0
    ) -> None:
        """
        Wait for all specified nodes to reach ONLINE state.
        
        Args:
            nodes: List of nodes to wait for
            timeout: Maximum wait time in seconds
            poll_interval: Time between state checks
            
        Raises:
            TimeoutError: If nodes don't reach online state within timeout
        """
        logger.info("waiting_for_nodes_online",
                   node_count=len(nodes),
                   timeout=timeout)
        
        start_time = asyncio.get_event_loop().time()
        nodes_online: Set[int] = set()
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            
            if elapsed >= timeout:
                missing = len(nodes) - len(nodes_online)
                
                # DIAGNOSTIC: Before raising timeout, collect detailed diagnostics
                logger.error("nodes_online_timeout",
                           elapsed=f"{elapsed:.1f}s",
                           online=len(nodes_online),
                           total=len(nodes),
                           missing=missing)
                
                # Collect diagnostic info for each missing node
                for node in nodes:
                    if node.node_id not in nodes_online:
                        try:
                            container_name = f"{self.project_name}-node-{node.node_id}"
                            container = self.docker_client.containers.get(container_name)
                            container.reload()
                            
                            # Get container status
                            logger.error("node_timeout_diagnostic",
                                       node_id=node.node_id,
                                       container_status=container.status,
                                       note="Node failed to reach ONLINE state")
                            
                            # Try to get network status output
                            try:
                                exit_code, output = container.exec_run(
                                    f"{self.cli_path} net get status -net {self.network_name}",
                                    demux=False
                                )
                                output_str = output.decode('utf-8') if output else ""
                                logger.error("node_network_status_at_timeout",
                                           node_id=node.node_id,
                                           exit_code=exit_code,
                                           output=output_str[:500],
                                           note="Network status at timeout")
                            except Exception as e:
                                logger.error("failed_to_get_network_status_at_timeout",
                                           node_id=node.node_id,
                                           error=str(e))
                            
                            # Get recent logs for errors
                            try:
                                logs = container.logs(tail=50).decode('utf-8', errors='ignore')
                                error_lines = [l for l in logs.split('\n') if any(keyword in l.lower() for keyword in ['error', 'fail', 'not found', 'can\'t init', 'no networks'])]
                                if error_lines:
                                    logger.error("node_logs_errors_at_timeout",
                                               node_id=node.node_id,
                                               error_lines=error_lines[-10:],
                                               note="Recent errors from node logs")
                            except Exception as e:
                                logger.error("failed_to_get_logs_at_timeout",
                                           node_id=node.node_id,
                                           error=str(e))
                        except Exception as e:
                            logger.error("failed_to_collect_node_diagnostics",
                                       node_id=node.node_id,
                                       error=str(e))
                
                raise TimeoutError(
                    f"Nodes failed to reach ONLINE state after {elapsed:.1f}s. "
                    f"Only {len(nodes_online)}/{len(nodes)} nodes are online."
                )
            
            # Check state of each node
            for node in nodes:
                if node.node_id in nodes_online:
                    continue  # Already online
                
                state = await self._get_node_state(node.node_id)
                
                # DIAGNOSTIC: Log current state for debugging
                if elapsed >= 10.0 and elapsed % 10.0 < poll_interval:  # Log every ~10 seconds
                    logger.info("node_state_check_during_wait",
                               node_id=node.node_id,
                               state=state.value,
                               elapsed=f"{elapsed:.1f}s",
                               note="Waiting for node to reach ONLINE state")
                
                if state in [NodeState.ONLINE, NodeState.LINKS_CONNECTING, 
                            NodeState.LINKS_ESTABLISHED]:
                    nodes_online.add(node.node_id)
                    logger.debug("node_online", node_id=node.node_id, state=state.value)
                elif state == NodeState.UNKNOWN:
                    # DIAGNOSTIC: If state is UNKNOWN, try to get more info
                    logger.debug("node_state_unknown_during_wait",
                               node_id=node.node_id,
                               elapsed=f"{elapsed:.1f}s",
                               note="Node state is UNKNOWN - may indicate network not loaded or container issue")
            
            # All nodes online?
            if len(nodes_online) == len(nodes):
                logger.info("all_nodes_online",
                           elapsed=f"{elapsed:.1f}s",
                           count=len(nodes))
                return
            
            # Log progress periodically
            if int(elapsed) % 10 == 0 and int(elapsed) > 0:
                logger.info("nodes_online_progress",
                           elapsed=f"{elapsed:.1f}s",
                           online=len(nodes_online),
                           total=len(nodes))
            
            await asyncio.sleep(poll_interval)
    
    async def wait_for_nodes_offline(
        self,
        nodes: List[NodeConfig],
        timeout: float = 30.0,
        poll_interval: float = 1.0
    ) -> None:
        """
        Wait for all specified nodes to reach OFFLINE state.
        
        Args:
            nodes: List of nodes to wait for
            timeout: Maximum wait time in seconds
            poll_interval: Time between state checks
            
        Raises:
            TimeoutError: If nodes don't reach offline state within timeout
        """
        logger.info("waiting_for_nodes_offline",
                   node_count=len(nodes),
                   timeout=timeout)
        
        start_time = asyncio.get_event_loop().time()
        nodes_offline: Set[int] = set()
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            
            if elapsed >= timeout:
                missing = len(nodes) - len(nodes_offline)
                logger.error("nodes_offline_timeout",
                           elapsed=f"{elapsed:.1f}s",
                           offline=len(nodes_offline),
                           total=len(nodes),
                           missing=missing)
                raise TimeoutError(
                    f"Nodes failed to reach OFFLINE state after {elapsed:.1f}s. "
                    f"Only {len(nodes_offline)}/{len(nodes)} nodes are offline."
                )
            
            # Check state of each node
            for node in nodes:
                if node.node_id in nodes_offline:
                    continue  # Already offline
                
                state = await self._get_node_state(node.node_id)
                if state == NodeState.OFFLINE:
                    nodes_offline.add(node.node_id)
                    logger.debug("node_offline", node_id=node.node_id)
            
            # All nodes offline?
            if len(nodes_offline) == len(nodes):
                logger.info("all_nodes_offline",
                           elapsed=f"{elapsed:.1f}s",
                           count=len(nodes))
                return
            
            await asyncio.sleep(poll_interval)
    
    async def _get_node_state(self, node_id: int) -> NodeState:
        """
        Get current network state of a running node via CLI.
        
        CRITICAL: This checks NETWORK state (online/offline/etc), NOT container state.
        The container must be running for this check to work.
        
        Args:
            node_id: Node ID (1, 2, 3, ...)
            
        Returns:
            Current node network state, or UNKNOWN if container is not running
        """
        container_name = f"{self.project_name}-node-{node_id}"
        
        try:
            container = self.docker_client.containers.get(container_name)
            
            # Check if container is actually running
            # If "go offline" stops the container, we should NOT try to query it
            container.reload()  # Refresh container state
            if container.status != 'running':
                logger.debug("container_not_running",
                           node_id=node_id,
                           status=container.status)
                return NodeState.UNKNOWN
            
            # Execute 'net get status' command with network name
            # CRITICAL: Must specify -net parameter for multi-network nodes
            exit_code, output = container.exec_run(
                f"{self.cli_path} net get status -net {self.network_name}",
                demux=False
            )
            
            if exit_code != 0:
                logger.debug("cli_command_failed",
                           node_id=node_id,
                           exit_code=exit_code,
                           note="net get status command failed - network may not be loaded")
                return NodeState.UNKNOWN
            
            output_str = output.decode('utf-8') if output else ""
            
            # DIAGNOSTIC: If output contains errors, log them
            if "error" in output_str.lower() or "not found" in output_str.lower():
                logger.warning("network_status_error_in_output",
                             node_id=node_id,
                             output_preview=output_str[:300],
                             note="Network status command returned error - network may not be initialized")
            
            # Try JSON format first (6.0+):
            # [{"status":{"states":{"current":"NET_STATE_ONLINE","target":"NET_STATE_ONLINE"}}}]
            try:
                parsed = json.loads(output_str.strip())
                if isinstance(parsed, list) and len(parsed) > 0:
                    item = parsed[0]
                    current_str = None
                    if isinstance(item, dict):
                        status = item.get("status", item)
                        states = status.get("states", {})
                        current_str = states.get("current")
                    if current_str:
                        for state in NodeState:
                            if state.value == current_str:
                                logger.debug("node_state_detected",
                                           node_id=node_id,
                                           state=state.value,
                                           format="json")
                                return state
            except (json.JSONDecodeError, TypeError, KeyError):
                pass
            
            # Fall back to text format (5.x):
            #   current: NET_STATE_ONLINE
            for line in output_str.split('\n'):
                line_stripped = line.strip()
                if line_stripped.startswith('current:'):
                    for state in NodeState:
                        if state.value in line_stripped:
                            logger.debug("node_state_detected",
                                       node_id=node_id,
                                       state=state.value,
                                       format="text")
                            return state
            
            logger.debug("state_not_parsed",
                       node_id=node_id,
                       output_preview=output_str[:200])
            
            if output_str:
                logger.warning("failed_to_parse_node_state",
                             node_id=node_id,
                             output_preview=output_str[:500],
                             note="Could not parse network state from CLI output - check network initialization")
            
            return NodeState.UNKNOWN
            
        except docker.errors.NotFound:
            logger.debug("container_not_found",
                        container=container_name,
                        note="Container may have stopped")
            return NodeState.UNKNOWN
        except Exception as e:
            logger.warning("state_check_failed",
                          node_id=node_id,
                          error=str(e))
            return NodeState.UNKNOWN
    
    async def phased_startup(
        self,
        root_nodes: List[NodeConfig],
        master_nodes: List[NodeConfig],
        compose_manager,
        wait_timeout: float = 60.0
    ) -> None:
        """
        Perform phased network startup: ROOT → MASTER.
        
        Process:
        1. Start ROOT nodes
        2. Wait for ROOT nodes to reach ONLINE state
        3. Start MASTER nodes
        4. Wait for MASTER nodes to reach ONLINE state
        
        Args:
            root_nodes: List of ROOT nodes
            master_nodes: List of MASTER nodes
            compose_manager: DockerComposeManager instance
            wait_timeout: Timeout for each phase
        """
        # Phase 1: Start ROOT nodes
        logger.info("=== PHASED STARTUP: Phase 1 - ROOT Nodes ===")
        root_services = [f"node-{n.node_id}" for n in root_nodes]
        
        logger.info("starting_root_nodes", services=root_services)
        compose_manager.up(services=root_services, detach=True, wait=False)
        
        # Wait for ROOT nodes to be ONLINE
        await self.wait_for_nodes_online(root_nodes, timeout=wait_timeout)
        logger.info("root_nodes_online_and_stable")
        
        # Phase 2: Start MASTER nodes
        logger.info("=== PHASED STARTUP: Phase 2 - MASTER Nodes ===")
        master_services = [f"node-{n.node_id}" for n in master_nodes]
        
        logger.info("starting_master_nodes", services=master_services)
        compose_manager.up(services=master_services, detach=True, wait=False)
        
        # Wait for MASTER nodes to be ONLINE
        await self.wait_for_nodes_online(master_nodes, timeout=wait_timeout)
        logger.info("master_nodes_online_and_stable")
        
        logger.info("phased_startup_complete",
                   root_count=len(root_nodes),
                   master_count=len(master_nodes))
    
    async def wait_for_nodes_to_have_addresses(
        self,
        nodes: List[NodeConfig],
        timeout: float = 60.0,
        poll_interval: float = 2.0
    ) -> None:
        """
        Wait until all specified nodes have generated their node addresses.
        
        Args:
            nodes: List of nodes to check
            timeout: Maximum time to wait (seconds)
            poll_interval: Time between checks (seconds)
            
        Raises:
            TimeoutError: If not all nodes have addresses within timeout
        """
        import time
        start_time = time.time()
        node_ids = [n.node_id for n in nodes]
        
        while time.time() - start_time < timeout:
            nodes_with_addresses = 0
            
            for node in nodes:
                try:
                    container_name = f"{self.project_name}-node-{node.node_id}"
                    container = self.docker_client.containers.get(container_name)
                    
                    # Check container status
                    container.reload()
                    if container.status != 'running':
                        continue
                    
                    # Try to get node address
                    exit_code, output = container.exec_run(
                        f"{self.cli_path} node dump -net {self.network_name}",
                        demux=False
                    )
                    
                    if exit_code == 0 and output:
                        output_str = output.decode('utf-8', errors='ignore')
                        # Check if output contains "Node addr:"
                        if 'Node addr:' in output_str or 'Node address:' in output_str:
                            nodes_with_addresses += 1
                            logger.debug("node_has_address", node_id=node.node_id)
                
                except Exception as e:
                    logger.debug("failed_to_check_node_address",
                               node_id=node.node_id,
                               error=str(e))
                    continue
            
            if nodes_with_addresses == len(nodes):
                logger.info("all_nodes_have_addresses",
                           count=nodes_with_addresses,
                           elapsed=round(time.time() - start_time, 1))
                return
            
            # Log progress
            elapsed = time.time() - start_time
            if elapsed > 5.0:  # Only log after 5 seconds
                logger.info("waiting_for_node_addresses",
                           ready=nodes_with_addresses,
                           total=len(nodes),
                           elapsed=round(elapsed, 1))
            
            await asyncio.sleep(poll_interval)
        
        # Timeout
        raise TimeoutError(
            f"Nodes failed to generate addresses after {timeout}s. "
            f"Only {nodes_with_addresses}/{len(nodes)} nodes have addresses."
        )

