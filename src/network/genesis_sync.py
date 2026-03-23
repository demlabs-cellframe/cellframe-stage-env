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
from src.utils.logger import get_logger
from src.utils.project import make_container_name
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
            container_name = make_container_name(f"node-{first_node.node_id}")
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
            
            # CRITICAL: Wait for chain loading to complete before processing datum
            # Chain files are loaded asynchronously, and events need to be in events_lasts_unlinked
            # before mempool_proc can create new events (otherwise "Nothing to link" error)
            logger.info("waiting_for_dag_events_before_mempool_proc",
                       datum=datum_hash[:16],
                       note="Waiting for chain files to load and DAG events to be available for linking")
            
            # Poll for DAG events to be loaded
            import time
            start_wait = time.time()
            events_loaded = False
            
            while time.time() - start_wait < 60.0:  # Max 60s wait
                exit_code_events, stdout_events, _ = self._exec_cli(
                    first_node.node_id,
                    f"dag event list -net {self.network_name} -chain zerochain -from events -limit 5",
                    check_output=False
                )
                
                if exit_code_events == 0 and stdout_events:
                    # Check for "total_events: N" where N > 0
                    import re
                    events_match = re.search(r'total_events:\s*(\d+)', stdout_events, re.IGNORECASE)
                    if events_match:
                        events_count = int(events_match.group(1))
                        if events_count > 0:
                            logger.info("dag_events_loaded_ready_for_mempool_proc",
                                       datum=datum_hash[:16],
                                       events_count=events_count,
                                       elapsed=f"{time.time() - start_wait:.1f}s",
                                       note="DAG events loaded - events_lasts_unlinked should be populated")
                            events_loaded = True
                            break
                
                await asyncio.sleep(2)
            
            if not events_loaded:
                logger.warning("dag_events_not_loaded_proceeding_anyway",
                             datum=datum_hash[:16],
                             elapsed=f"{time.time() - start_wait:.1f}s",
                             note="DAG events not loaded within timeout - mempool_proc may fail with 'Nothing to link'")
            
            # Step 2: Trigger mempool_proc on ALL root nodes (including first node)
            # CRITICAL: For DAG-PoA, each node needs to process datum to create events
            # Track processing results
            proc_results = {}  # node_id -> (success, error_message)
            logger.info("starting_mempool_proc_on_all_nodes",
                       datum=datum_hash[:16],
                       node_count=len(root_nodes),
                       note="Starting mempool_proc on all root nodes")
            
            for node in root_nodes:
                container_name = make_container_name(f"node-{node.node_id}")
                try:
                    node_container = self.docker_client.containers.get(container_name)
                    
                    # Check if container is still running
                    node_container.reload()
                    if node_container.status != 'running':
                        logger.warning("container_not_running", 
                                      node=f"node{node.node_id}",
                                      status=node_container.status)
                        proc_results[node.node_id] = (False, f"Container not running: {node_container.status}")
                        continue
                    
                    logger.info("triggering_mempool_proc", 
                               node=f"node{node.node_id}", 
                               datum=datum_hash[:16],
                               container=container_name,
                               container_status=node_container.status)
                    
                    # CRITICAL: Execute mempool_proc and capture all output
                    logger.debug("executing_mempool_proc_command",
                               node=f"node{node.node_id}",
                               datum=datum_hash[:16],
                               command=f"mempool_proc -datum {datum_hash} -net {self.network_name} -chain zerochain")
                    
                    exit_code, stdout, stderr = self._exec_cli(
                        node.node_id,
                        f"mempool_proc -datum {datum_hash} -net {self.network_name} -chain zerochain",
                        check_output=False
                    )
                    
                    logger.debug("mempool_proc_raw_output",
                               node=f"node{node.node_id}",
                               datum=datum_hash[:16],
                               exit_code=exit_code,
                               stdout_len=len(stdout) if stdout else 0,
                               stderr_len=len(stderr) if stderr else 0,
                               stdout_preview=stdout[:500] if stdout else "empty",
                               stderr_preview=stderr[:500] if stderr else "empty")
                    
                    # CRITICAL: Parse JSON response to check for errors
                    # mempool_proc returns JSON-RPC response which may contain errors even if exit_code == 0
                    import json
                    has_error = False
                    error_message = None
                    if stdout:
                        try:
                            # Try to parse JSON response
                            response_data = json.loads(stdout)
                            if isinstance(response_data, list) and len(response_data) > 0:
                                # Check for error field in response
                                if isinstance(response_data[0], dict):
                                    if "error" in response_data[0]:
                                        has_error = True
                                        error_info = response_data[0]["error"]
                                        if isinstance(error_info, dict):
                                            error_message = error_info.get("message", str(error_info))
                                        else:
                                            error_message = str(error_info)
                                    elif "result" in response_data[0]:
                                        # Success - check result message
                                        result = response_data[0].get("result", "")
                                        if isinstance(result, str) and ("processed" in result.lower() or "success" in result.lower()):
                                            logger.debug("mempool_proc_result_success",
                                                       node=f"node{node.node_id}",
                                                       datum=datum_hash[:16],
                                                       result=result[:200])
                        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                            # Not JSON or invalid format - log but continue
                            logger.debug("mempool_proc_response_not_json",
                                       node=f"node{node.node_id}",
                                       datum=datum_hash[:16],
                                       error=str(e)[:200])
                    
                    # CRITICAL: Log full output for debugging
                    logger.info("mempool_proc_result",
                               node=f"node{node.node_id}",
                               datum=datum_hash[:16],
                               exit_code=exit_code,
                               has_json_error=has_error,
                               error_message=error_message[:500] if error_message else None,
                               stdout=stdout[:1000] if stdout else "empty",
                               stderr=stderr[:1000] if stderr else "empty",
                               note="Full mempool_proc output - check if datum was processed correctly")
                    
                    # Track result
                    proc_success = False
                    proc_error = None
                    
                    if exit_code == 0 and not has_error:
                        logger.info("mempool_proc_success", node=f"node{node.node_id}", datum=datum_hash[:16])
                        # CRITICAL: Check if datum was actually processed by checking node logs
                        # If datum was rejected (e.g., "already added to round"), it won't create event
                        if stderr and ("already added" in stderr.lower() or "drop it" in stderr.lower()):
                            proc_error = f"Datum rejected: {stderr[:200]}"
                            logger.warning("mempool_proc_datum_rejected",
                                         node=f"node{node.node_id}",
                                         datum=datum_hash[:16],
                                         stderr=stderr[:500],
                                         note="Datum was rejected by mempool_proc - may already be processed or invalid")
                        else:
                            proc_success = True
                    else:
                        error_note = "mempool_proc failed"
                        if has_error:
                            error_note = f"mempool_proc returned JSON error: {error_message[:200] if error_message else 'unknown'}"
                            proc_error = error_message or "Unknown JSON error"
                        else:
                            proc_error = f"Exit code: {exit_code}, stderr: {stderr[:200] if stderr else 'none'}"
                        logger.warning("mempool_proc_failed", 
                                     node=f"node{node.node_id}", 
                                     exit_code=exit_code,
                                     has_json_error=has_error,
                                     error_message=error_message[:500] if error_message else None,
                                     stderr=stderr[:500] if stderr else "none",
                                     stdout=stdout[:500] if stdout else "none",
                                     note=error_note)
                    
                    proc_results[node.node_id] = (proc_success, proc_error)
                        
                except docker.errors.NotFound:
                    logger.warning("container_not_found_skipping", 
                                  node=f"node{node.node_id}",
                                  container=container_name)
                    proc_results[node.node_id] = (False, f"Container not found: {container_name}")
                    continue
                except Exception as e:
                    logger.error("failed_to_trigger_mempool_proc", 
                               node=f"node{node.node_id}", 
                               error=str(e),
                               error_type=type(e).__name__,
                               traceback=str(e))
                    proc_results[node.node_id] = (False, f"Exception: {type(e).__name__}: {str(e)}")
            
            # CRITICAL: Check if any mempool_proc succeeded before waiting
            # If all mempool_proc calls failed, datum won't be processed
            successful_proc_count = sum(1 for success, _ in proc_results.values() if success)
            failed_proc_count = len(proc_results) - successful_proc_count
            
            logger.info("mempool_proc_summary",
                       datum=datum_hash[:16],
                       total_nodes=len(root_nodes),
                       successful=successful_proc_count,
                       failed=failed_proc_count,
                       results={node_id: {"success": success, "error": error[:200] if error else None} 
                               for node_id, (success, error) in proc_results.items()},
                       note="Summary of mempool_proc results across all root nodes")
            
            if successful_proc_count == 0:
                logger.error("all_mempool_proc_failed",
                           datum=datum_hash[:16],
                           failed_count=failed_proc_count,
                           note="CRITICAL: All mempool_proc calls failed! Datum will not be processed. "
                                "Check mempool_proc_result logs above for error details. "
                                "Common causes: 1) Node role insufficient (need MASTER or higher), "
                                "2) Datum already processed, 3) Datum verification failed, "
                                "4) Network not synchronized")
                
                # Collect node logs for diagnostic
                logger.info("collecting_node_logs_for_diagnostic", datum=datum_hash[:16])
                for node in root_nodes[:3]:  # Check first 3 nodes
                    try:
                        container = self.docker_client.containers.get(make_container_name(f"node-{node.node_id}"))
                        logs = container.logs(tail=300).decode('utf-8', errors='replace')
                        
                        # Filter logs for mempool_proc related messages
                        import re
                        mempool_lines = []
                        for line in logs.split('\n'):
                            if re.search(r'(mempool|Start mempool|Nothing to link|already added|Configuration mismatch)', line, re.IGNORECASE):
                                mempool_lines.append(line)
                        
                        logger.error("node_logs_after_failed_mempool_proc",
                                   node=f"node{node.node_id}",
                                   datum=datum_hash[:16],
                                   mempool_related_logs='\n'.join(mempool_lines) if mempool_lines else "No mempool-related logs found",
                                   full_logs_preview=logs[-1000:],
                                   note="Check for 'Nothing to link', 'already added to round', or consensus errors")
                    except Exception as e:
                        logger.warning("failed_to_get_node_logs", 
                                     node=f"node{node.node_id}", 
                                     error=str(e))
            
            # CRITICAL: Wait a bit after mempool_proc to allow DAG event creation
            # DAG-PoA needs time to process datum and create new event
            logger.info("waiting_after_mempool_proc_for_dag_event_creation", datum=datum_hash[:16], wait_seconds=5)
            await asyncio.sleep(5)  # Increased wait time for DAG event creation
            
            # CRITICAL: Check if datum was removed from mempool on ALL root nodes
            # If datum is still in mempool after mempool_proc, it may not have been processed
            logger.info("checking_datum_status_after_mempool_proc", datum=datum_hash[:16])
            datum_still_in_mempool_on_any_node = False
            for node in root_nodes:
                exit_code_mempool_check, stdout_mempool_check, _ = self._exec_cli(
                    node.node_id,
                    f"mempool list -net {self.network_name} -chain zerochain",
                    check_output=False
                )
                if exit_code_mempool_check == 0 and stdout_mempool_check:
                    datum_in_mempool = datum_hash.lower() in stdout_mempool_check.lower()
                    if datum_in_mempool:
                        datum_still_in_mempool_on_any_node = True
                        logger.warning("datum_still_in_mempool_after_proc",
                                     node=f"node{node.node_id}",
                                     datum=datum_hash[:16],
                                     note="Datum still in mempool after mempool_proc on this node - may not have been processed correctly. "
                                          "This could indicate: 1) Datum was rejected (already processed), "
                                          "2) DAG-PoA consensus issue, 3) Network synchronization problem, "
                                          "4) Node role insufficient (need MASTER or higher)")
                    else:
                        logger.info("datum_removed_from_mempool_after_proc",
                                  node=f"node{node.node_id}",
                                  datum=datum_hash[:16],
                                  note="Datum removed from mempool on this node - processing started")
            
            if datum_still_in_mempool_on_any_node:
                logger.error("datum_not_processed_on_all_nodes",
                           datum=datum_hash[:16],
                           note="CRITICAL: Datum still in mempool on at least one node after mempool_proc. "
                                "This means mempool_proc did not successfully process the datum. "
                                "Check mempool_proc_result logs above for error details.")
            
            # Step 3: Wait for datum to be finalized in DAG (polling with timeout)
            logger.info("waiting_for_datum_in_dag", datum=datum_hash[:16], timeout=timeout)
            
            # CRITICAL: First check if datum is in mempool - if not, it will never be finalized
            logger.info("checking_datum_in_mempool_before_dag_wait", datum=datum_hash[:16])
            exit_code_mempool, stdout_mempool, _ = self._exec_cli(
                first_node.node_id,
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
                                 note="Datum not in mempool - may have been processed or removed")
            
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
                container_name = make_container_name(f"node-{node.node_id}")
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
