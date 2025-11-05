"""
Chain synchronization management for Cellframe stagenet.

Handles chain sync operations and datum processing.
"""

import asyncio
import re
from pathlib import Path
from typing import List, Optional

import docker

from .genesis_base import BaseGenesisManager
from .models import NodeConfig
from ..utils.logger import get_logger
from ..monitoring.waiter.chain_waiters import (
    ChainDataPropagationWaiter,
    NetworkSyncWaiter,
)
from ..monitoring.waiter.dag_waiters import DAGEventWaiter


logger = get_logger(__name__)


class ChainSyncManager(BaseGenesisManager):
    """
    Manages chain synchronization and datum processing.
    
    Responsibilities:
    - Network synchronization (all chains or specific chain)
    - Zerochain datum processing through DAG-PoA
    - Waiting for block creation
    
    Inherits from BaseGenesisManager:
    - _exec_cli(): CLI command execution
    - _read_node_addr_from_cli(): Node address retrieval
    """
    
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
            
            # Step 2: Trigger mempool_proc on ALL root nodes (including first node)
            # CRITICAL: For DAG-PoA, each node needs to process datum to create events
            for node in root_nodes:
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
                    
                    logger.info("triggering_mempool_proc", node=f"node{node.node_id}", datum=datum_hash[:16])
                    
                    exit_code, stdout, stderr = self._exec_cli(
                        node.node_id,
                        f"mempool_proc -datum {datum_hash} -net {self.network_name} -chain zerochain",
                        check_output=False
                    )
                    
                    # CRITICAL: Log full output for debugging
                    logger.info("mempool_proc_result",
                               node=f"node{node.node_id}",
                               datum=datum_hash[:16],
                               exit_code=exit_code,
                               stdout=stdout[:1000] if stdout else "empty",
                               stderr=stderr[:1000] if stderr else "empty",
                               note="Full mempool_proc output - check if datum was processed correctly")
                    
                    if exit_code == 0:
                        logger.info("mempool_proc_success", node=f"node{node.node_id}", datum=datum_hash[:16])
                    else:
                        logger.warning("mempool_proc_failed", 
                                     node=f"node{node.node_id}", 
                                     exit_code=exit_code, 
                                     stderr=stderr[:500] if stderr else "none",
                                     stdout=stdout[:500] if stdout else "none")
                        
                except docker.errors.NotFound:
                    logger.warning("container_not_found_skipping", 
                                  node=f"node{node.node_id}",
                                  container=container_name)
                    continue
                except Exception as e:
                    logger.warning("failed_to_trigger_mempool_proc", node=f"node{node.node_id}", error=str(e))
            
            # CRITICAL: Wait a bit after mempool_proc to allow DAG event creation
            # DAG-PoA needs time to process datum and create new event
            logger.info("waiting_after_mempool_proc_for_dag_event_creation", datum=datum_hash[:16], wait_seconds=3)
            await asyncio.sleep(3)
            
            # Step 3: Wait for datum to be finalized in DAG (polling with timeout)
            logger.info("waiting_for_datum_in_dag", datum=datum_hash[:16], timeout=timeout)
            
            # CRITICAL: First check if datum is in mempool - if not, it will never be finalized
            logger.info("checking_datum_in_mempool_before_dag_wait", datum=datum_hash[:16])
            exit_code_mempool, stdout_mempool, _ = self._exec_cli(
                1,
                f"mempool list -net {self.network_name} -chain zerochain",
                check_output=False
            )
            if exit_code_mempool == 0 and stdout_mempool:
                if datum_hash.lower() in stdout_mempool.lower():
                    logger.info("datum_found_in_mempool", datum=datum_hash[:16])
                else:
                    logger.warning("datum_not_in_mempool", 
                                 datum=datum_hash[:16],
                                 mempool_preview=stdout_mempool[:500],
                                 note="Datum not in mempool - may not be created correctly")
            
            # Wait for datum to appear in DAG events
            waiter_dag_event = DAGEventWaiter(
                exec_cli=self._exec_cli,
                node_id=1,
                datum_hash=datum_hash,
                network_name=self.network_name,
                chain="zerochain",
                poll_interval=5.0
            )
            await waiter_dag_event.wait(timeout=float(timeout))
                
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
            
            # For chain-specific sync, verify by checking if chain has data
            if chain_name:
                logger.info("waiting_for_chain_data_propagation", chain=chain_name, timeout=timeout)
                
                waiter_chain_data = ChainDataPropagationWaiter(
                    exec_cli=self._exec_cli,
                    nodes=nodes,
                    network_name=self.network_name,
                    chain_name=chain_name,
                    poll_interval=5.0
                )
                await waiter_chain_data.wait(timeout=float(timeout))
            
            # For full network sync (sync all), check general status
            waiter_network_sync = NetworkSyncWaiter(
                exec_cli=self._exec_cli,
                docker_client=self.docker_client,
                nodes=nodes,
                network_name=self.network_name,
                poll_interval=5.0
            )
            await waiter_network_sync.wait(timeout=float(timeout))
            
        except Exception as e:
            logger.error("network_sync_error", error=str(e))
            raise
