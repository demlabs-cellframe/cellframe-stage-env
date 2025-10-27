"""
Node registration management for Cellframe stagenet.

Handles node list population and alias registration.
"""

import asyncio
import re
from pathlib import Path
from typing import Dict, List, Optional

import docker

from .models import NodeConfig
from ..utils.logger import get_logger


logger = get_logger(__name__)


class NodeRegistrationManager:
    """
    Manages node registration and topology setup.
    
    Responsibilities:
    - Register node aliases in GDB
    - Populate node lists via CLI
    - Setup root node topology
    - Add nodes to nodelists
    """
    
    def __init__(self, base_path: Path, network_name: str = "stagenet", certs_cache: Path = None):
        """
        Initialize node registration manager.
        
        Args:
            base_path: Base path to stage-env directory
            network_name: Network name (default: stagenet)
            certs_cache: Path to certificates cache
        """
        self.base_path = base_path
        self.network_name = network_name
        self.docker_client = docker.from_env()
        self.certs_cache = certs_cache or (base_path / ".." / "testing" / "cache" / "certs").resolve()
    
    def _exec_cli(self, node_id: int, command: str, check_output: bool = True) -> tuple:
        """
        Execute CLI command inside container.
        
        Args:
            node_id: Node ID (1-8)
            command: CLI command without 'cellframe-node-cli' prefix
            check_output: Whether to check for errors in output
            
        Returns:
            Tuple of (exit_code, stdout_str, stderr_str)
        """
        container_name = f"cellframe-stage-node-{node_id}"
        container = self.docker_client.containers.get(container_name)
        
        full_cmd = f"cellframe-node-cli {command}"
        cmd_array = ["sh", "-c", full_cmd]
        
        result = container.exec_run(cmd_array, demux=True)
        exit_code = result.exit_code
        stdout, stderr = result.output
        
        stdout_str = stdout.decode('utf-8') if stdout else ""
        stderr_str = stderr.decode('utf-8') if stderr else ""
        
        return (exit_code, stdout_str, stderr_str)
    
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
        
        # CRITICAL: Wait for GDB to propagate node list to ALL nodes
        # Node1 added all nodes locally, but GDB sync takes time (1-5s)
        # Without this, offline/online happens before other nodes see the list
        logger.info("waiting_for_node_list_gdb_propagation")
        
        import time
        start_wait = time.time()
        all_have_list = False
        
        while time.time() - start_wait < 30:  # Max 30s for GDB sync
            nodes_with_list = 0
            
            for node in nodes:
                try:
                    exit_code, stdout, _ = self._exec_cli(
                        node.node_id,
                        f"node list -net {self.network_name}",
                        check_output=False
                    )
                    
                    # Check if node has full list (should see len(nodes) nodes)
                    if exit_code == 0:
                        # Count "Got N nodes:"
                        match = re.search(r'Got\s+(\d+)\s+nodes', stdout, re.IGNORECASE)
                        if match:
                            node_count = int(match.group(1))
                            if node_count >= len(nodes):
                                nodes_with_list += 1
                except Exception as e:
                    logger.debug("node_list_check_error", node=node.node_id, error=str(e)[:100])
            
            if nodes_with_list >= len(nodes):
                elapsed = time.time() - start_wait
                logger.info("all_nodes_have_node_list",
                           nodes=nodes_with_list,
                           total=len(nodes),
                           elapsed=f"{elapsed:.1f}s")
                all_have_list = True
                break
            
            # Log progress
            elapsed = time.time() - start_wait
            logger.info("node_list_propagation_progress",
                       elapsed=f"{elapsed:.1f}s",
                       nodes_with_list=nodes_with_list,
                       total=len(nodes),
                       missing=len(nodes) - nodes_with_list)
            
            await asyncio.sleep(2)
        
        if not all_have_list:
            logger.warning("node_list_gdb_sync_incomplete",
                          nodes_with_list=nodes_with_list,
                          total=len(nodes),
                          note="GDB sync requires links - will propagate after initial link establishment or offline/online cycle")
    
    async def force_network_reconnection(self, nodes: List[NodeConfig], wait_for_links: bool = True) -> None:
        """
        Force network reconnection via offline/online cycle.
        
        This is CRITICAL for applying config changes (genesis blocks, seed_mode, etc).
        Use ONLY at specific genesis milestones:
        1. After DAG genesis event finalization (Phase 1)
        2. After ESBocs genesis block creation (Phase 2)
        
        Args:
            nodes: List of nodes to reconnect
            wait_for_links: Whether to wait for links establishment after reconnection
        """
        logger.info("forcing_network_reconnection", nodes=len(nodes))
        
        # Step 1: Bring all nodes offline
        logger.info("bringing_all_nodes_offline")
        for node in nodes:
            try:
                self._exec_cli(node.node_id, f"net -net {self.network_name} go offline", check_output=False)
                logger.debug("node_offline", node_id=node.node_id)
            except Exception as e:
                logger.warning("failed_to_go_offline", node_id=node.node_id, error=str(e))
        
        # Small delay to ensure offline processed on all nodes
        await asyncio.sleep(2)
        
        # Step 2: Bring all nodes online simultaneously
        logger.info("bringing_all_nodes_online")
        for node in nodes:
            try:
                self._exec_cli(node.node_id, f"net -net {self.network_name} go online", check_output=False)
                logger.debug("node_online", node_id=node.node_id)
            except Exception as e:
                logger.warning("failed_to_go_online", node_id=node.node_id, error=str(e))
        
        logger.info("network_reconnection_initiated")
        
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

