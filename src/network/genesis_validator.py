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
from ..utils.logger import get_logger


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
        node: NodeConfig
    ) -> None:
        """
        Create validator order for a node.
        
        Args:
            container: Docker container to execute commands in
            node: Node configuration
        """
        # Certificate name for this validator
        # NOTE: Must use pvt. prefix for private key! Both validator_create and CLI commands need it.
        # CRITICAL: MASTER nodes are node4,5,6 but cert indices are 0,1,2
        # Match cert-generator.c logic: cert_idx = is_root_node ? i : (i - 3)
        if node.node_id <= 3:
            # ROOT nodes: node1,2,3 → cert indices 0,1,2
            validator_idx = node.node_id - 1
            cert_name = f"pvt.{self.network_name}.root.{validator_idx}"
        else:
            # MASTER nodes: node4,5,6 → cert indices 0,1,2
            validator_idx = node.node_id - 4  # node4→0, node5→1, node6→2
            cert_name = f"pvt.{self.network_name}.master.{validator_idx}"
        
        # Read node address with retry logic
        node_addr = self._read_node_addr_from_cli(node.node_id)
        
        if not node_addr:
            logger.error("cannot_create_order_no_node_addr",
                        node_id=node.node_id)
            return
        
        logger.info("read_node_address",
                   node_id=node.node_id,
                   node_addr=node_addr)
        
        # Order parameters
        # value_min and value_max in datoshi (1 token = 10^18 datoshi)
        # For testing, use 100 tokens min, 10000 tokens max
        value_min = "100000000000000000000"  # 100 tokens
        value_max = "10000000000000000000000"  # 10000 tokens
        tax = "10.0"  # 10.0% tax (must be float с точкой)
        
        # Use unified CLI method
        logger.info("creating_validator_order",
                   node_id=node.node_id,
                   cert=cert_name,
                   node_addr=node_addr)
        
        try:
            exit_code, stdout_str, stderr_str = self._exec_cli(
                node.node_id,
                f"srv_stake order create validator -net {self.network_name} -value_min {value_min} -value_max {value_max} -tax {tax} -cert {cert_name} -node_addr {node_addr} -H hex",
                check_output=False
            )
            
            if exit_code != 0:
                logger.error("order_creation_failed",
                           node_id=node.node_id,
                           exit_code=exit_code,
                           stdout=stdout_str,
                           stderr=stderr_str)
                raise RuntimeError(f"Failed to create order for node {node.node_id}: {stderr_str}")
            
            logger.info("validator_order_created",
                       node_id=node.node_id,
                       cert=cert_name,
                       output=stdout_str.strip())
            
        except Exception as e:
            logger.exception("order_creation_exception",
                           node_id=node.node_id,
                           error=str(e))
            raise
    
    async def verify_validator_orders(
        self,
        nodes: List[NodeConfig],
        expected_count: int,
        timeout: float = 30.0
    ) -> None:
        """
        Verify that all nodes can see all validator orders.
        
        This is critical for ESBocs consensus - if nodes don't see orders,
        they will switch off validator mode and refuse to create blocks.
        
        Args:
            nodes: List of NodeConfig objects to check
            expected_count: Expected number of validator orders
            timeout: Maximum time to wait for orders to appear
        
        Raises:
            RuntimeError: If orders are not visible after timeout
        """
        from time import time
        
        logger.info("verifying_orders_on_all_nodes",
                   node_count=len(nodes),
                   expected_orders=expected_count)
        
        start_time = time()
        all_nodes_ready = False
        
        while time() - start_time < timeout:
            nodes_with_orders = 0
            
            for node in nodes:
                try:
                    # Query orders list on this node
                    exit_code, stdout_str, stderr_str = self._exec_cli(
                        node.node_id,
                        f"srv_stake order list -net {self.network_name}",
                        check_output=False
                    )
                    
                    if exit_code == 0:
                        # Count orders in output (simple heuristic: count "Order" keyword)
                        order_count = stdout_str.count("Order")
                        
                        # DETAILED LOGGING: Show actual output for debugging
                        logger.info("order_list_output",
                                   node_id=node.node_id,
                                   order_count=order_count,
                                   output_preview=stdout_str[:500] if stdout_str else "EMPTY")
                        
                        if order_count >= expected_count:
                            nodes_with_orders += 1
                            logger.debug("node_sees_all_orders",
                                       node_id=node.node_id,
                                       order_count=order_count)
                        else:
                            logger.warning("node_missing_orders",
                                       node_id=node.node_id,
                                       found=order_count,
                                       expected=expected_count,
                                       full_output=stdout_str)
                    else:
                        logger.warning("order_list_failed",
                                     node_id=node.node_id,
                                     exit_code=exit_code,
                                     stderr=stderr_str[:200],
                                     stdout=stdout_str[:200])
                
                except Exception as e:
                    logger.warning("order_check_exception",
                                 node_id=node.node_id,
                                 error=str(e))
            
            # Check if all nodes see all orders
            if nodes_with_orders == len(nodes):
                all_nodes_ready = True
                logger.info("all_nodes_see_all_orders",
                          elapsed=f"{time() - start_time:.1f}s")
                break
            
            # Log progress
            logger.info("order_visibility_progress",
                       elapsed=f"{time() - start_time:.1f}s",
                       nodes_ready=nodes_with_orders,
                       total=len(nodes))
            
            await asyncio.sleep(2.0)
        
        if not all_nodes_ready:
            raise RuntimeError(
                f"Not all nodes see validator orders after {timeout}s. "
                f"Only {nodes_with_orders}/{len(nodes)} nodes ready."
            )
    
    async def sync_orders_across_network(self, nodes: List[NodeConfig]) -> None:
        """
        Synchronize GDB to propagate validator orders across network.
        
        Validator orders are stored in local GDB but require explicit sync
        to be visible on all nodes.
        
        Args:
            nodes: List of nodes to sync
        """
        logger.info("syncing_validator_orders", node_count=len(nodes))
        
        for node in nodes:
            try:
                exit_code, stdout_str, stderr_str = self._exec_cli(
                    node.node_id,
                    f"net -net {self.network_name} go sync",
                    check_output=False
                )
                
                if exit_code == 0:
                    logger.debug("gdb_sync_triggered", node_id=node.node_id)
                else:
                    logger.warning("gdb_sync_failed",
                                 node_id=node.node_id,
                                 exit_code=exit_code,
                                 stderr=stderr_str[:200])
            except Exception as e:
                logger.warning("gdb_sync_exception",
                             node_id=node.node_id,
                             error=str(e))
        
        # Wait for sync to propagate
        logger.info("waiting_for_gdb_sync_propagation")
        await asyncio.sleep(5.0)
        logger.info("gdb_sync_completed")

