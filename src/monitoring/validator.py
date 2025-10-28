"""
Validator order monitoring service.

Monitors validator order visibility across network nodes.
"""

from pathlib import Path
from typing import Dict, List, Any

import docker

from .base import BaseMonitor, MonitorConfig
from ..network.models import NodeConfig
from ..utils.logger import get_logger


logger = get_logger(__name__)


class ValidatorMonitor(BaseMonitor):
    """
    Monitors validator order visibility across network.
    
    Checks that all nodes can see all expected validator orders.
    Critical for ESBocs consensus - nodes without visible orders
    will switch off validator mode.
    """
    
    def __init__(
        self,
        nodes: List[NodeConfig],
        network_name: str,
        expected_order_count: int,
        config: MonitorConfig
    ):
        """
        Initialize validator monitor.
        
        Args:
            nodes: List of nodes to check
            network_name: Network name (e.g., "stagenet")
            expected_order_count: Expected number of validator orders
            config: Monitor configuration
        """
        super().__init__(config)
        self.nodes = nodes
        self.network_name = network_name
        self.expected_order_count = expected_order_count
        self.docker_client = docker.from_env()
        
        # Track per-node state
        self.node_states: Dict[int, Dict[str, Any]] = {}
    
    def _exec_cli(self, node_id: int, command: str) -> tuple[int, str, str]:
        """
        Execute CLI command in node container.
        
        Args:
            node_id: Node ID (1-8)
            command: CLI command without 'cellframe-node-cli' prefix
            
        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        container_name = f"cellframe-stage-node-{node_id}"
        try:
            container = self.docker_client.containers.get(container_name)
            
            exit_code, output = container.exec_run(
                f"cellframe-node-cli {command}",
                demux=True
            )
            
            stdout_bytes, stderr_bytes = output if isinstance(output, tuple) else (output, b"")
            stdout_str = stdout_bytes.decode('utf-8') if stdout_bytes else ""
            stderr_str = stderr_bytes.decode('utf-8') if stderr_bytes else ""
            
            return exit_code, stdout_str, stderr_str
            
        except docker.errors.NotFound:
            return 1, "", f"Container {container_name} not found"
        except Exception as e:
            return 1, "", str(e)
    
    async def _check_condition(self) -> tuple[bool, Dict[str, Any]]:
        """
        Check if all nodes see all validator orders.
        
        Returns:
            (all_nodes_ready, state_info)
        """
        nodes_with_orders = 0
        self.node_states.clear()
        
        for node in self.nodes:
            try:
                exit_code, stdout_str, stderr_str = self._exec_cli(
                    node.node_id,
                    f"srv_stake order list -net {self.network_name}"
                )
                
                if exit_code == 0:
                    # Count orders in output
                    order_count = stdout_str.count("Order")
                    has_all_orders = order_count >= self.expected_order_count
                    
                    self.node_states[node.node_id] = {
                        "order_count": order_count,
                        "has_all": has_all_orders,
                        "output_preview": stdout_str[:200] if stdout_str else "EMPTY"
                    }
                    
                    if has_all_orders:
                        nodes_with_orders += 1
                else:
                    self.node_states[node.node_id] = {
                        "order_count": 0,
                        "has_all": False,
                        "error": f"exit_code={exit_code}",
                        "stderr": stderr_str[:100]
                    }
            
            except Exception as e:
                self.node_states[node.node_id] = {
                    "order_count": 0,
                    "has_all": False,
                    "error": str(e)
                }
        
        all_ready = nodes_with_orders == len(self.nodes)
        
        state = {
            "nodes_ready": nodes_with_orders,
            "total_nodes": len(self.nodes),
            "expected_orders": self.expected_order_count,
            "node_states": self.node_states
        }
        
        return all_ready, state
    
    def _log_progress(self, elapsed: float, state: Dict[str, Any]) -> None:
        """Log validator order visibility progress."""
        nodes_ready = state["nodes_ready"]
        total = state["total_nodes"]
        expected = state["expected_orders"]
        
        logger.info("validator_orders_progress",
                   elapsed=f"{elapsed:.1f}s",
                   nodes_ready=f"{nodes_ready}/{total}",
                   expected_orders=expected)
        
        # Log detailed per-node state if verbose
        if self.config.verbose:
            for node_id, node_state in state["node_states"].items():
                if node_state.get("has_all"):
                    logger.debug("node_orders_ok",
                               node_id=node_id,
                               count=node_state["order_count"])
                else:
                    logger.warning("node_orders_missing",
                                 node_id=node_id,
                                 found=node_state["order_count"],
                                 expected=expected,
                                 error=node_state.get("error"),
                                 output=node_state.get("output_preview"))

