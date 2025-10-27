"""
Chain synchronization management for Cellframe stagenet.

Handles chain sync operations and datum processing.
"""

import asyncio
import re
from pathlib import Path
from typing import List

import docker

from .models import NodeConfig
from ..utils.logger import get_logger


logger = get_logger(__name__)


class ChainSyncManager:
    """
    Manages chain synchronization and datum processing.
    
    Responsibilities:
    - Network synchronization (all chains or specific chain)
    - Zerochain datum processing through DAG-PoA
    - Waiting for block creation
    """
    
    def __init__(self, base_path: Path, network_name: str = "stagenet"):
        """
        Initialize chain sync manager.
        
        Args:
            base_path: Base path to stage-env directory
            network_name: Network name (default: stagenet)
        """
        self.base_path = base_path
        self.network_name = network_name
        self.docker_client = docker.from_env()
    
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
    
    async def process_zerochain_datum(self, datum_hash: str, root_nodes: List[NodeConfig], timeout: int = 120) -> None:
        """
        Process datum through DAG-PoA consensus on zerochain.
        
        Workflow:
        1. Wait for datum in mempool on first root node
        2. Trigger mempool_proc on remaining root nodes
        3. Wait for datum finalization in DAG events
        
        Args:
            datum_hash: Datum hash to process
            root_nodes: List of root node configurations
            timeout: Timeout for each stage
            
        Raises:
            RuntimeError: If datum processing fails
        """
        logger.info("processing_zerochain_datum", datum=datum_hash[:16], root_count=len(root_nodes))
        
        if not root_nodes:
            raise RuntimeError("No root nodes provided for zerochain datum processing")
        
        try:
            # Step 1: Wait for datum to appear in mempool on first root node
            first_node = root_nodes[0]
            container_name = f"cellframe-stage-node-{first_node.node_id}"
            container = self.docker_client.containers.get(container_name)
            
            logger.debug("waiting_for_datum_in_mempool", node=f"node{first_node.node_id}", datum=datum_hash[:16])
            
            # Poll mempool for datum
            import time
            start_time = time.time()
            found = False
            
            while time.time() - start_time < timeout:
                exit_code, stdout_str, stderr_str = self._exec_cli(
                    first_node.node_id,
                    f"mempool_list -net {self.network_name} -chain zerochain",
                    check_output=False
                )
                
                if datum_hash.lower() in stdout_str.lower():
                    found = True
                    logger.info("datum_appeared_in_mempool", node=f"node{first_node.node_id}", elapsed=f"{time.time() - start_time:.1f}s")
                    break
                
                await asyncio.sleep(1)
            
            if not found:
                raise RuntimeError(f"Datum {datum_hash[:16]}... did not appear in mempool within {timeout}s")
            
            # Step 2: Trigger mempool_proc on remaining root nodes
            for node in root_nodes[1:]:
                container_name = f"cellframe-stage-node-{node.node_id}"
                try:
                    node_container = self.docker_client.containers.get(container_name)
                    
                    # Check if container is still running
                    node_container.reload()
                    if node_container.status != 'running':
                        logger.warning("container_not_running", 
                                      node=f"node{node.node_id}",
                                      status=node_container.status)
                        continue
                    
                    logger.debug("triggering_mempool_proc", node=f"node{node.node_id}", datum=datum_hash[:16])
                    
                    exit_code, stdout, stderr = self._exec_cli(
                        node.node_id,
                        f"mempool_proc -datum {datum_hash} -net {self.network_name} -chain zerochain",
                        check_output=False
                    )
                    
                    if exit_code == 0:
                        logger.info("mempool_proc_triggered", node=f"node{node.node_id}")
                    else:
                        logger.warning("mempool_proc_failed", node=f"node{node.node_id}", exit_code=exit_code, stderr=stderr)
                        
                except docker.errors.NotFound:
                    logger.warning("container_not_found_skipping", 
                                  node=f"node{node.node_id}",
                                  container=container_name)
                    continue
                except Exception as e:
                    logger.warning("failed_to_trigger_mempool_proc", node=f"node{node.node_id}", error=str(e))
            
            # Step 3: Wait for datum to be finalized in DAG (polling with timeout)
            logger.info("waiting_for_datum_in_dag", datum=datum_hash[:16], timeout=timeout)
            dag_check_start = time.time()
            found_in_dag = False
            last_log_time = time.time()
            
            while time.time() - dag_check_start < timeout:
                # For DAG-PoA, check if datum is in events (not blocks!)
                exit_code, stdout_events_str, _ = self._exec_cli(
                    1,
                    f"dag event list -net {self.network_name} -chain zerochain -from events -limit 20",
                    check_output=False
                )
                
                # Log progress every 10 seconds
                elapsed = time.time() - dag_check_start
                if time.time() - last_log_time >= 10:
                    logger.info("dag_finalization_progress", 
                               datum=datum_hash[:16],
                               elapsed=f"{elapsed:.1f}s",
                               event_list_preview=stdout_events_str[:300] if stdout_events_str else "empty",
                               exit_code=exit_code)
                    last_log_time = time.time()
                
                # Check if any events appeared (indicates DAG is working)
                total_match = re.search(r'total events:\s*(\d+)', stdout_events_str, re.IGNORECASE)
                if total_match and int(total_match.group(1)) > 0:
                    found_in_dag = True
                    logger.info("datum_finalized_in_dag", 
                               datum=datum_hash[:16],
                               total_events=int(total_match.group(1)),
                               elapsed=f"{time.time() - dag_check_start:.1f}s")
                    return
                
                await asyncio.sleep(5)
            
            if not found_in_dag:
                raise RuntimeError(f"Datum {datum_hash[:16]}... was not finalized in DAG within {timeout}s")
                
        except Exception as e:
            logger.error("zerochain_datum_processing_error", error=str(e))
            raise
    
    async def sync_network(self, nodes: List[NodeConfig], chain_name: str = None, timeout: int = 120) -> None:
        """
        Synchronize all nodes in the network.
        
        Triggers sync on all nodes and waits for completion.
        
        Args:
            nodes: List of all node configurations
            chain_name: Specific chain to sync (e.g., "zerochain", "main"), or None for all chains
            timeout: Timeout in seconds for sync completion
            
        Raises:
            RuntimeError: If sync fails or times out
        """
        sync_target = f"chain {chain_name}" if chain_name else "all"
        logger.info("synchronizing_network", node_count=len(nodes), target=sync_target, timeout=timeout)
        
        try:
            # Trigger sync on all nodes
            for node in nodes:
                container_name = f"cellframe-stage-node-{node.node_id}"
                try:
                    container = self.docker_client.containers.get(container_name)
                    
                    logger.debug("triggering_sync", node=f"node{node.node_id}", target=sync_target)
                    
                    # Build sync command
                    sync_cmd = f"net -net {self.network_name} sync {sync_target}"
                    
                    exit_code, stdout_str, stderr_str = self._exec_cli(
                        node.node_id,
                        sync_cmd,
                        check_output=False
                    )
                    
                    if exit_code == 0:
                        logger.debug("sync_triggered", node=f"node{node.node_id}")
                    else:
                        logger.warning("sync_trigger_failed", node=f"node{node.node_id}", exit_code=exit_code)
                        
                except Exception as e:
                    logger.warning("failed_to_trigger_sync", node=f"node{node.node_id}", error=str(e))
            
            # Monitor sync progress
            import time
            start_time = time.time()
            check_interval = 5
            
            # For chain-specific sync, verify by checking if chain has data
            if chain_name:
                logger.info("waiting_for_chain_data_propagation", chain=chain_name, timeout=timeout)
                
                while time.time() - start_time < timeout:
                    synced_count = 0
                    
                    for node in nodes:
                        try:
                            # Check if node has any data in the chain
                            is_dag_chain = chain_name.lower() in ["zerochain", "zero", "0"]
                            
                            if is_dag_chain:
                                # For DAG: check total events > 0
                                exit_code_check, stdout_check, _ = self._exec_cli(
                                    node.node_id,
                                    f"dag event list -net {self.network_name} -chain {chain_name} -from events -limit 1",
                                    check_output=False
                                )
                                
                                # Parse "total events: N"
                                total_match = re.search(r'total events:\s*(\d+)', stdout_check, re.IGNORECASE) if stdout_check else None
                                total_events = int(total_match.group(1)) if total_match else 0
                                has_data = exit_code_check == 0 and total_events > 0
                                
                                # DIAGNOSTIC: Log full output for first check to debug
                                if time.time() - start_time < 10 and node == nodes[0]:
                                    logger.info("dag_event_list_diagnostic",
                                               node=f"node{node.node_id}",
                                               exit_code=exit_code_check,
                                               total_events=total_events,
                                               full_output=stdout_check if stdout_check else "EMPTY")
                            else:
                                # For blockchain: check if any blocks exist
                                exit_code_check, stdout_check, _ = self._exec_cli(
                                    node.node_id,
                                    f"block list -net {self.network_name} -chain {chain_name} -last 1",
                                    check_output=False
                                )
                                
                                # Look for "block #" in output
                                has_data = exit_code_check == 0 and "block #" in stdout_check.lower()
                            
                            if has_data:
                                synced_count += 1
                                logger.debug("node_has_chain_data", 
                                           node=f"node{node.node_id}",
                                           chain=chain_name,
                                           preview=stdout_check[:100] if stdout_check else "empty")
                            else:
                                # Log why node doesn't have data
                                logger.debug("node_missing_chain_data",
                                           node=f"node{node.node_id}",
                                           exit_code=exit_code_check,
                                           output_preview=stdout_check[:200] if stdout_check else "EMPTY")
                                
                        except Exception as e:
                            logger.debug("failed_to_check_chain_data", node=f"node{node.node_id}", error=str(e)[:100])
                    
                    if synced_count >= len(nodes):  # All nodes have data
                        logger.info("chain_data_propagated", chain=chain_name, synced=synced_count, total=len(nodes), elapsed=f"{time.time() - start_time:.1f}s")
                        return
                    
                    # Log progress every iteration
                    logger.info("chain_sync_progress", 
                               chain=chain_name,
                               synced=synced_count,
                               total=len(nodes),
                               elapsed=f"{time.time() - start_time:.1f}s",
                               missing=len(nodes) - synced_count)
                    await asyncio.sleep(check_interval)
                
                # Timeout reached - CRITICAL ERROR!
                logger.error("chain_sync_timeout_critical",
                            chain=chain_name,
                            elapsed=timeout,
                            synced=synced_count,
                            total=len(nodes),
                            missing=len(nodes) - synced_count)
                raise RuntimeError(f"Chain {chain_name} sync timeout: only {synced_count}/{len(nodes)} nodes have data after {timeout}s")
            
            # For full network sync (sync all), check general status
            while time.time() - start_time < timeout:
                all_synced = True
                sync_status = {}
                
                for node in nodes:
                    container_name = f"cellframe-stage-node-{node.node_id}"
                    try:
                        container = self.docker_client.containers.get(container_name)
                        
                        exit_code_status, stdout_str, stderr_str = self._exec_cli(
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
                        logger.warning("failed_to_check_sync_status", node=f"node{node.node_id}", error=str(e))
                        all_synced = False
                        sync_status[f"node{node.node_id}"] = "error"
                
                if all_synced:
                    logger.info("network_synchronized", elapsed=f"{time.time() - start_time:.1f}s")
                    return
                
                logger.debug("sync_progress", status=sync_status, elapsed=f"{time.time() - start_time:.1f}s")
                await asyncio.sleep(check_interval)
            
            # Timeout reached
            logger.warning("sync_timeout", elapsed=timeout, final_status=sync_status)
            # Don't raise - sync may complete eventually
            
        except Exception as e:
            logger.error("network_sync_error", error=str(e))
            raise
    
    async def wait_for_first_block(self, chain_name: str, timeout: int = 60) -> None:
        """
        Wait for first block to be created in blockchain chain.
        
        Polls 'block list' until at least one block appears.
        
        Args:
            chain_name: Blockchain chain name (e.g., "main", "kelvin")
            timeout: Timeout in seconds
            
        Raises:
            RuntimeError: If no block appears within timeout
        """
        logger.info("waiting_for_first_block", chain=chain_name, timeout=timeout)
        
        import time
        start_time = time.time()
        check_interval = 3
        
        while time.time() - start_time < timeout:
            try:
                exit_code, stdout_str, _ = self._exec_cli(
                    1,  # Check on node1
                    f"block list -net {self.network_name} -chain {chain_name} -last 1",
                    check_output=False
                )
                
                if exit_code == 0 and "block #" in stdout_str.lower():
                    elapsed = time.time() - start_time
                    logger.info("first_block_appeared", chain=chain_name, elapsed=f"{elapsed:.1f}s")
                    return
                
                # Log progress every 15s
                elapsed = time.time() - start_time
                if int(elapsed) % 15 == 0 and elapsed > 1:
                    logger.info("waiting_for_block_progress", 
                               chain=chain_name,
                               elapsed=f"{elapsed:.1f}s",
                               output_preview=stdout_str[:100] if stdout_str else "empty")
                
            except Exception as e:
                logger.debug("block_check_error", error=str(e)[:100])
            
            await asyncio.sleep(check_interval)
        
        # Timeout
        raise RuntimeError(f"No blocks appeared in {chain_name} after {timeout}s")

