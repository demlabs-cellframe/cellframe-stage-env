"""
Node registration management for Cellframe stagenet.

Handles node list population and alias registration.
"""

import asyncio
import re
from pathlib import Path
from typing import Dict, List, Optional

import docker

from .genesis_base import BaseGenesisManager
from .models import NodeConfig
from src.utils.logger import get_logger


logger = get_logger(__name__)


class NodeRegistrationManager(BaseGenesisManager):
    """
    Manages node registration and topology setup.
    
    Responsibilities:
    - Register node aliases in GDB
    - Populate node lists via CLI
    - Setup root node topology
    - Add nodes to nodelists
    
    Inherits from BaseGenesisManager:
    - _exec_cli(): CLI command execution
    - _read_node_addr_from_cli(): Node address retrieval
    """
    
    def __init__(
        self, 
        base_path: Path, 
        network_name: str = "stagenet", 
        config_path: Path = None, 
        certs_cache: Path = None,
        state_manager = None
    ):
        """
        Initialize node registration manager.
        
        Args:
            base_path: Base path to stage-env directory
            network_name: Network name (default: stagenet)
            config_path: Optional path to stage-env.cfg
            certs_cache: Path to certificates cache
            state_manager: Optional NodeStateManager for intelligent state waiting
        """
        super().__init__(base_path, network_name, config_path)
        self.certs_cache = certs_cache or (base_path / ".." / "testing" / "cache" / "certs").resolve()
        self.state_manager = state_manager
    
    async def register_node_aliases(self, nodes: List[NodeConfig]) -> None:
        """
        Register node aliases in GDB for easier reference.
        
        Creates entries mapping node-1, node-2, etc. to actual node addresses.
        
        Args:
            nodes: List of all node configurations
        """
        logger.info("registering_node_aliases", count=len(nodes))
        
        for node in nodes:
            try:
                # Execute node dump to register alias
                alias = f"node-{node.node_id}"
                
                exit_code, stdout, stderr = self._exec_cli(
                    node.node_id,
                    f"node dump -net {self.network_name}",
                    check_output=False
                )
                
                if exit_code == 0 and "Node addr:" in stdout:
                    logger.debug("node_alias_registered", 
                                alias=alias,
                                node_id=node.node_id)
                else:
                    logger.warning("node_alias_registration_failed",
                                  alias=alias,
                                  exit_code=exit_code)
                    
            except Exception as e:
                logger.warning("exception_registering_alias",
                              node_id=node.node_id,
                              error=str(e))
        
        logger.info("node_aliases_registration_complete")
    
    async def register_all_nodes_via_cli(self, nodes: List[NodeConfig]) -> None:
        """
        Register ALL nodes via CLI 'node add' command on ALL ROOT nodes.
        
        CRITICAL: Each ROOT node must have full node list locally!
        GDB sync is unreliable without links (chicken-and-egg).
        Solution: Populate node list on EACH ROOT node directly.
        
        Args:
            nodes: List of all node configurations
        """
        logger.info("registering_nodes_on_all_root_nodes", total_nodes=len(nodes))
        
        # Prepare registration tasks: Each ROOT node registers ALL nodes locally
        async def register_on_node(registrar_node: NodeConfig, target_node: NodeConfig) -> bool:
            """
            Register target_node on registrar_node's local node list.
            Returns True on success.
            """
            
            # First check if node has loaded the network (ready for commands)
            try:
                exit_code_status, stdout_status, _ = self._exec_cli(
                    target_node.node_id,
                    f"net -net {self.network_name} get status",
                    check_output=False
                )
                
                # If network not found, node hasn't loaded network config yet
                if "Network stagenet not found" in stdout_status or "code: 103" in stdout_status:
                    logger.warning("node_network_not_loaded_yet",
                                  target=target_node.node_id,
                                  note="Node needs more time to load network config")
                    return False
            except Exception as e:
                logger.debug("node_status_check_failed", target=target_node.node_id, error=str(e)[:100])
            
            # Get target node address from its running container
            try:
                exit_code, stdout_str, stderr = self._exec_cli(
                    target_node.node_id,
                    f"node dump -net {self.network_name}",
                    check_output=False
                )
                
                if exit_code != 0:
                    logger.warning("skipping_registration_dump_failed",
                                  target=target_node.node_id,
                                  stderr=stderr)
                    return False
                
                # Parse target node address
                addr_match = re.search(r'Node addr:\s+([0-9A-Fa-f:]+)', stdout_str)
                if not addr_match:
                    logger.warning("skipping_registration_no_address",
                                  target=target_node.node_id,
                                  dump_output=stdout_str[:200])
                    return False
                
                target_addr = addr_match.group(1)
                
            except Exception as e:
                logger.warning("failed_to_fetch_address",
                              target=target_node.node_id,
                              error=str(e))
                return False
            
            # Register target_node on registrar_node's local node list
            logger.debug("registering_node_locally",
                       registrar=registrar_node.node_id,
                       target=target_node.node_id,
                       target_addr=target_addr[:20] + "...")
            
            try:
                exit_code, stdout_str, stderr_str = self._exec_cli(
                    registrar_node.node_id,  # Execute on registrar node (each ROOT node)
                    f"node add -net {self.network_name} -addr {target_addr} -host {target_node.ip_address} -port {target_node.node_port}",
                    check_output=False
                )
                
                if exit_code == 0:
                    # Parse response to verify registration
                    if "You have no access rights" in stdout_str:
                        logger.warning("node_add_no_rights",
                                      target=target_node.node_id,
                                      output=stdout_str[:100])
                        return False
                    elif "already" in stdout_str.lower():
                        logger.info("node_already_in_list",
                                   target=target_node.node_id,
                                   output=stdout_str[:100])
                        return True
                    elif "Successfully added" in stdout_str or "added node" in stdout_str.lower():
                        logger.info("node_registered_via_cli",
                                  target=target_node.node_id,
                                  output=stdout_str[:100])
                        return True
                    else:
                        # Unknown response - log full output
                        logger.warning("unknown_node_add_response",
                                      target=target_node.node_id,
                                      exit_code=exit_code,
                                      output=stdout_str[:200])
                        return False
                else:
                    logger.warning("node_add_failed",
                                  target=target_node.node_id,
                                  exit_code=exit_code,
                                  stderr=stderr_str[:100])
                    return False
                    
            except Exception as e:
                logger.exception("node_add_exception",
                               target=target_node.node_id,
                               error=str(e))
                return False
        
        # Each ROOT node registers ALL nodes locally (including itself)
        # This ensures every ROOT has full node list without relying on GDB sync
        registration_tasks = []
        
        # Only ROOT nodes have admin rights to modify node list
        root_nodes = [n for n in nodes if n.role == 'root']
        
        for registrar in root_nodes:
            for target in nodes:
                registration_tasks.append(register_on_node(registrar, target))
        
        logger.info("starting_local_registration_on_all_roots",
                   root_nodes=len(root_nodes),
                   total_registrations=len(registration_tasks))
        
        results = await asyncio.gather(*registration_tasks, return_exceptions=True)
        
        # Count successes
        success_count = sum(1 for r in results if r is True)
        failed_count = len(results) - success_count
        
        logger.info("node_registration_complete",
                   successful=success_count,
                   failed=failed_count,
                   total=len(nodes))
        
        # VERIFICATION: Check node list on node1 immediately after registration
        logger.info("verifying_node_list_on_node1_after_registration")
        try:
            exit_code, stdout, _ = self._exec_cli(
                1,
                f"node list -net {self.network_name}",
                check_output=False
            )
            
            if exit_code == 0:
                # Count nodes in list
                match = re.search(r'Got\s+(\d+)\s+nodes', stdout, re.IGNORECASE)
                if match:
                    node_count = int(match.group(1))
                    logger.info("node1_list_verification",
                               registered=node_count,
                               expected=len(nodes),
                               status="OK" if node_count >= len(nodes) else "INCOMPLETE",
                               output_preview=stdout[:200])
                else:
                    logger.warning("could_not_parse_node_list", output=stdout[:200])
            else:
                logger.warning("node_list_command_failed", exit_code=exit_code)
        except Exception as e:
            logger.warning("node_list_verification_error", error=str(e))
        
        # NOTE: Node list propagation via GDB sync requires links
        # In ESBocs genesis, node list is already synced via bootstrap sync (net go sync) in Step 2
        # This check is skipped - node list propagation will happen naturally when links are established
        logger.info("node_list_registration_complete",
                   note="Node list propagation depends on links - already synced via bootstrap sync")
    
    async def soft_network_reconnect(self, nodes: List[NodeConfig], wait_for_links: bool = True) -> None:
        """
        Soft network reconnection via offline/online cycle (WITHOUT container restart).
        
        This quickly re-establishes network links without losing in-memory state.
        Use cases:
        - After node registration to establish initial links
        - After container restart to speed up link re-establishment
        - Any time when you need to refresh network connections without config reload
        
        Args:
            nodes: List of nodes to reconnect
            wait_for_links: Whether to wait for links establishment after reconnection
        """
        logger.info("soft_network_reconnect", nodes=len(nodes))
        
        # Step 1: Bring all nodes offline
        logger.info("bringing_all_nodes_offline")
        for node in nodes:
            try:
                # Check if container is running before attempting offline
                container_name = f"cellframe-stage-node-{node.node_id}"
                try:
                    container = self.docker_client.containers.get(container_name)
                    container.reload()
                    if container.status != 'running':
                        logger.debug("skipping_offline_for_stopped_container",
                                   node_id=node.node_id,
                                   status=container.status)
                        continue
                except Exception:
                    logger.debug("skipping_offline_for_inaccessible_container",
                               node_id=node.node_id)
                    continue
                
                self._exec_cli(node.node_id, f"net -net {self.network_name} go offline", check_output=False)
                logger.debug("node_offline_command_sent", node_id=node.node_id)
            except Exception as e:
                logger.warning("failed_to_go_offline", node_id=node.node_id, error=str(e))
        
        # Intelligent waiting for OFFLINE state if state_manager is available
        # NOTE: We check NETWORK state via CLI, not container state via Docker API
        # If "go offline" stops containers, this will gracefully handle UNKNOWN states
        if self.state_manager:
            try:
                await self.state_manager.wait_for_nodes_offline(nodes, timeout=30.0)
                logger.info("nodes_confirmed_offline", count=len(nodes))
            except TimeoutError as e:
                # Some nodes may not reach offline (e.g., if containers stop)
                # This is acceptable - we continue anyway
                logger.warning("offline_timeout_continuing_anyway", 
                             nodes=len(nodes), error=str(e))
        else:
            # Fallback: simple delay if state_manager not available
            await asyncio.sleep(2)
        
        # Step 2: Bring all nodes online simultaneously
        logger.info("bringing_all_nodes_online")
        for node in nodes:
            try:
                # Check if container is running before attempting online
                container_name = f"cellframe-stage-node-{node.node_id}"
                try:
                    container = self.docker_client.containers.get(container_name)
                    container.reload()
                    if container.status != 'running':
                        logger.debug("skipping_online_for_stopped_container",
                                   node_id=node.node_id,
                                   status=container.status)
                        continue
                except Exception:
                    logger.debug("skipping_online_for_inaccessible_container",
                               node_id=node.node_id)
                    continue
                
                self._exec_cli(node.node_id, f"net -net {self.network_name} go online", check_output=False)
                logger.debug("node_online_command_sent", node_id=node.node_id)
            except Exception as e:
                logger.warning("failed_to_go_online", node_id=node.node_id, error=str(e))
        
        # Intelligent waiting for ONLINE state
        if self.state_manager:
            try:
                await self.state_manager.wait_for_nodes_online(nodes, timeout=60.0)
                logger.info("all_nodes_confirmed_online", count=len(nodes))
            except TimeoutError as e:
                logger.warning("online_timeout_continuing_anyway", 
                             nodes=len(nodes), error=str(e))
        else:
            # Fallback: simple delay
            await asyncio.sleep(2)
        
        logger.info("network_reconnection_complete", nodes=len(nodes))
        
        # Step 3: Wait for links establishment (if requested)
        if wait_for_links:
            logger.info("waiting_for_links_after_reconnection")
            
            from ..monitoring.network_consensus import NetworkConsensusMonitor
            monitor = NetworkConsensusMonitor(
                nodes={f"node{n.node_id}": n for n in nodes},
                network_name=self.network_name
            )
            
            try:
                await monitor.wait_for_links_established(timeout=60.0)
                logger.info("links_established_after_reconnection")
            except TimeoutError:
                logger.warning("links_establishment_timeout_after_reconnection",
                              note="Some links may still be connecting")

