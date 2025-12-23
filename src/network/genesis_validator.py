"""
Validator order management for Cellframe stagenet.

Handles validator order creation and verification for ESBocs consensus.
"""

import asyncio
from pathlib import Path
from typing import List

import docker

from .genesis_base import BaseGenesisManager
from .models import NodeConfig
from src.utils.logger import get_logger


logger = get_logger(__name__)


class ValidatorManager(BaseGenesisManager):
    """
    Manages validator orders for ESBocs consensus.
    
    Responsibilities:
    - Create validator orders for MASTER nodes
    - Verify order visibility across network
    - Sync validator orders via GDB
    
    Inherits from BaseGenesisManager:
    - _exec_cli(): CLI command execution
    - _read_node_addr_from_cli(): Node address retrieval via CLI
    """
    
    async def create_validator_order(
        self,
        container: docker.models.containers.Container,
        node: NodeConfig,
        root_nodes_count: int = 4
    ) -> None:
        """
        Create validator order for a node.
        
        Args:
            container: Docker container to execute commands in
            node: Node configuration
            root_nodes_count: Number of root nodes (for calculating master_idx)
        """
        # Certificate name for this validator
        # NOTE: Certificate format is {network}.{role}.pvt.{idx}
        if node.is_seed_node:
            # ROOT nodes: cert indices 0,1,2,... 
            validator_idx = node.node_id - 1
            cert_name = f"{self.network_name}.root.pvt.{validator_idx}"
        else:
            # MASTER nodes: cert indices 0,1,2,...
            # master_idx = node_id - root_nodes_count - 1
            validator_idx = node.node_id - root_nodes_count - 1
            cert_name = f"{self.network_name}.master.pvt.{validator_idx}"
        
        # Read node address with retry logic
        node_addr = self._read_node_addr_from_cli(node.node_id)
        
        if not node_addr:
            logger.error("cannot_create_order_no_node_addr",
                        node_id=node.node_id)
            return
        
        logger.info("read_node_address",
                   node_id=node.node_id,
                   node_addr=node_addr)
        
        # CRITICAL: Create FEE order, not VALIDATOR order!
        # SDK ESBocs searches for order with srv_uid = DAP_CHAIN_NET_SRV_STAKE_POS_DELEGATE_ID (0x13) - fee order
        # NOT DAP_CHAIN_NET_SRV_STAKE_POS_DELEGATE_ORDERS (0x14) - validator order for stake delegation
        # See SDK: dap_chain_cs_esbocs.c:651
        #   if (l_order->srv_uid.uint64 != DAP_CHAIN_NET_SRV_STAKE_POS_DELEGATE_ID)
        #       continue;
        #
        # Fee order sets minimum fee for processing transactions (used by ESBocs for minimum_fee)
        # Format: srv_stake order create fee -net <net> -value <fee> -cert <cert>
        # CRITICAL: Value must be in datoshi (1 token = 1e+18 datoshi), like tests-in-docker
        fee_value = "0.1e+18"  # 0.1 tokens = 0.1e+18 datoshi minimum fee
        
        # Use unified CLI method
        logger.info("creating_fee_order_for_validator",
                   node_id=node.node_id,
                   cert=cert_name,
                   node_addr=node_addr,
                   fee=fee_value,
                   note="Creating FEE order (srv_uid=0x13) for ESBocs minimum_fee, not validator order (srv_uid=0x14)")
        
        try:
            # CRITICAL: Do NOT specify "fee" explicitly - SDK defaults to fee order
            # tests-in-docker uses: srv_stake order create -net ... -value ... -cert ...
            # SDK logic: if no type specified, defaults to CMD_CREATE_FEE (line 1697)
            exit_code, stdout_str, stderr_str = self._exec_cli(
                node.node_id,
                f"srv_stake order create -net {self.network_name} -value {fee_value} -cert {cert_name} -H hex",
                check_output=False
            )
            
            if exit_code != 0:
                logger.error("order_creation_failed",
                           node_id=node.node_id,
                           exit_code=exit_code,
                           stdout=stdout_str,
                           stderr=stderr_str)
                raise RuntimeError(f"Failed to create order for node {node.node_id}: {stderr_str}")
            
            # Extract order hash from output if available
            order_hash = None
            if stdout_str:
                import re
                hash_match = re.search(r'0x[a-fA-F0-9]{64}', stdout_str)
                if hash_match:
                    order_hash = hash_match.group(0)
            
            logger.info("fee_order_created_for_validator",
                       node_id=node.node_id,
                       cert=cert_name,
                       validator_idx=validator_idx,
                       order_hash=order_hash,
                       fee_value=fee_value,
                       output=stdout_str.strip())
            
            # CRITICAL: Verify that order was created with correct certificate
            # Wait a moment for order to be stored in GDB, then verify it exists
            await asyncio.sleep(1.0)
            try:
                exit_code_check, stdout_check, stderr_check = self._exec_cli(
                    node.node_id,
                    f"srv_stake order list -net {self.network_name}",
                    check_output=False
                )
                if exit_code_check == 0 and stdout_check:
                    # Check if our order is in the list
                    if order_hash and order_hash.lower() in stdout_check.lower():
                        logger.debug("validator_order_verified_in_gdb",
                                   node_id=node.node_id,
                                   cert=cert_name,
                                   order_hash=order_hash)
                    else:
                        logger.warning("validator_order_not_found_in_gdb_yet",
                                     node_id=node.node_id,
                                     cert=cert_name,
                                     order_hash=order_hash,
                                     note="Order may need more time to sync")
                else:
                    logger.warning("cannot_verify_order_in_gdb",
                                 node_id=node.node_id,
                                 exit_code=exit_code_check,
                                 stderr=stderr_check[:200] if stderr_check else "")
            except Exception as verify_e:
                logger.warning("order_verification_exception",
                            node_id=node.node_id,
                            error=str(verify_e)[:100],
                            note="Order creation succeeded but verification failed")
            
        except Exception as e:
            logger.exception("order_creation_exception",
                           node_id=node.node_id,
                           cert=cert_name,
                           validator_idx=validator_idx,
                           error=str(e))
            raise
    
    async def sync_orders_across_network(self, nodes: List[NodeConfig]) -> None:
        """
        Synchronize GDB to propagate validator orders across network.
        
        Validator orders are stored in local GDB but require explicit sync
        to be visible on all nodes.
        
        Args:
            nodes: List of nodes to sync
        """
        logger.info("syncing_validator_orders", node_count=len(nodes))
        
        # CRITICAL: Only sync nodes that are actually running
        # Skip nodes that are crashed or not ready
        running_nodes = []
        for node in nodes:
            container_name = f"cellframe-stage-node-{node.node_id}"
            try:
                container = self.docker_client.containers.get(container_name)
                container.reload()
                if container.status == 'running':
                    running_nodes.append(node)
                else:
                    logger.warning("skipping_sync_for_non_running_node",
                                 node_id=node.node_id,
                                 status=container.status)
            except Exception as e:
                logger.warning("failed_to_check_node_status_for_sync",
                             node_id=node.node_id,
                             error=str(e)[:100])
        
        if not running_nodes:
            logger.warning("no_running_nodes_for_gdb_sync",
                         total_nodes=len(nodes))
            return
        
        logger.info("syncing_gdb_on_running_nodes", 
                   running_count=len(running_nodes),
                   total_count=len(nodes))
        
        for node in running_nodes:
            try:
                # CRITICAL: Check network state before sync
                # Exit code 253 may indicate network is not ready for sync
                exit_code_check, stdout_check, stderr_check = self._exec_cli(
                    node.node_id,
                    f"net -net {self.network_name} get status",
                    check_output=False
                )
                
                if exit_code_check != 0:
                    logger.warning("node_not_ready_for_sync",
                                node_id=node.node_id,
                                exit_code=exit_code_check,
                                stderr=stderr_check[:200] if stderr_check else "")
                    continue
                
                # Check if network is ONLINE or can be synced
                # If network is OFFLINE, try to bring it online first
                if stdout_check:
                    stdout_lower = stdout_check.lower()
                    if "offline" in stdout_lower and "online" not in stdout_lower:
                        logger.debug("network_offline_bringing_online_before_sync",
                                   node_id=node.node_id)
                        exit_code_online, _, _ = self._exec_cli(
                            node.node_id,
                            f"net -net {self.network_name} go online",
                            check_output=False
                        )
                        if exit_code_online == 0:
                            await asyncio.sleep(2.0)  # Wait for network to come online
                        else:
                            logger.warning("failed_to_bring_network_online",
                                         node_id=node.node_id,
                                         exit_code=exit_code_online)
                            continue
                
                exit_code, stdout_str, stderr_str = self._exec_cli(
                    node.node_id,
                    f"net -net {self.network_name} go sync",
                    check_output=False
                )
                
                if exit_code == 0:
                    logger.debug("gdb_sync_triggered", node_id=node.node_id)
                elif exit_code == 253:
                    # Exit code 253: network may not be ready or in wrong state
                    logger.warning("gdb_sync_failed_network_not_ready",
                                 node_id=node.node_id,
                                 exit_code=exit_code,
                                 note="Network may be offline or not initialized")
                else:
                    logger.warning("gdb_sync_failed",
                                 node_id=node.node_id,
                                 exit_code=exit_code,
                                 stderr=stderr_str[:200] if stderr_str else "")
            except Exception as e:
                logger.warning("gdb_sync_exception",
                             node_id=node.node_id,
                             error=str(e))
        
        # Wait for sync to propagate and verify orders are actually synced
        logger.info("waiting_for_gdb_sync_propagation")
        await asyncio.sleep(10.0)  # Increased from 5.0 to 10.0 for proper GDB sync
        
        # CRITICAL: Verify orders are actually synced in GDB before proceeding
        # ESBocs loads orders during initialization, so we need to ensure orders
        # are available in GDB before ESBocs checks for them
        logger.info("verifying_orders_in_gdb_after_sync")
        max_retries = 5
        retry_delay = 2.0
        for attempt in range(max_retries):
            all_synced = True
            for node in nodes:
                try:
                    exit_code, stdout, stderr = self._exec_cli(
                        node.node_id,
                        f"srv_stake order list -net {self.network_name}",
                        check_output=False
                    )
                    if exit_code == 0 and stdout:
                        stdout_lower = stdout.lower()
                        order_count = stdout_lower.count("order:")
                        if order_count < len(nodes):
                            logger.debug("orders_not_fully_synced",
                                       node_id=node.node_id,
                                       order_count=order_count,
                                       expected=len(nodes),
                                       attempt=attempt + 1)
                            all_synced = False
                            break
                    else:
                        logger.debug("order_check_failed",
                                   node_id=node.node_id,
                                   exit_code=exit_code,
                                   attempt=attempt + 1)
                        all_synced = False
                        break
                except Exception as e:
                    logger.debug("order_check_exception",
                               node_id=node.node_id,
                               error=str(e)[:100],
                               attempt=attempt + 1)
                    all_synced = False
                    break
            
            if all_synced:
                logger.info("orders_verified_in_gdb", attempt=attempt + 1)
                break
            
            if attempt < max_retries - 1:
                logger.info("waiting_for_orders_to_sync", attempt=attempt + 1, retry_delay=retry_delay)
                await asyncio.sleep(retry_delay)
        
        logger.info("gdb_sync_completed")
    
