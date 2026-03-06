"""
Global context for scenario execution.

Provides centralized access to environment information that should be available
in all scenarios: node IPs, topology, network configuration, etc.
"""

from typing import Any, Dict, List, Optional
from pathlib import Path
import docker
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ScenarioGlobalContext:
    """
    Global context available in all scenario executions.
    
    Automatically collects and provides:
    - node_ips: Array of node IP addresses [ip1, ip2, ip3, ...]
    - node_ip: Map of node_id -> IP {node1: ip1, node2: ip2, ...}
    - network_name: Network name (e.g., 'stagenet')
    - topology_name: Topology template name
    - node_count: Total number of nodes
    - root_count, master_count, full_count: Node counts by role
    """
    
    def __init__(
        self,
        network_name: str,
        topology_name: str,
        docker_client: Optional[docker.DockerClient] = None,
        native_ticker: Optional[str] = None,
        node_port: int = 8079
    ):
        """
        Initialize global context.
        
        Args:
            network_name: Network name (e.g., 'stagenet')
            topology_name: Topology template name
            docker_client: Docker client for IP resolution (optional, will create if needed)
            native_ticker: Native token ticker (from config)
            node_port: Cellframe node listen port (from config, default 8079)
        """
        self.network_name = network_name
        self.topology_name = topology_name
        self.native_ticker = native_ticker
        self.node_port = node_port
        self._docker_client = docker_client or docker.from_env()
        
        # Cached node information
        self._node_ips: List[str] = []
        self._node_ip_map: Dict[str, str] = {}
        self._node_configs: List[Any] = []
        
        # Topology statistics
        self.node_count = 0
        self.root_count = 0
        self.master_count = 0
        self.full_count = 0
    
    def set_static_node_info(self, node_configs: List[Any]) -> None:
        """
        Pre-populate node information from topology config (before containers start).
        
        This sets node counts and static IPs from the configuration, allowing
        variables like all_nodes, root_nodes to be used in setup phase.
        
        Args:
            node_configs: List of NodeConfig objects
        """
        self._node_configs = node_configs
        
        # Calculate topology statistics
        self.node_count = len(node_configs)
        self.root_count = sum(1 for n in node_configs if n.role == 'root')
        self.master_count = sum(1 for n in node_configs if n.role == 'master')
        self.full_count = sum(1 for n in node_configs if n.role == 'full')
        
        # Pre-populate static IPs from node configs if available
        self._node_ips = []
        self._node_ip_map = {}
        
        for node in node_configs:
            # Check if node has a static IP configured
            if hasattr(node, 'ip') and node.ip:
                node_key = f"node{node.node_id}"
                self._node_ips.append(node.ip)
                self._node_ip_map[node_key] = node.ip
                # Also add with hyphen format for docker service names
                self._node_ip_map[f"node-{node.node_id}"] = node.ip
        
        logger.info("static_node_info_set",
                   node_count=self.node_count,
                   root_count=self.root_count,
                   master_count=self.master_count,
                   static_ips=len(self._node_ip_map))
    
    def collect_node_ips(self, node_configs: List[Any], wait_for_ips: bool = True) -> None:
        """
        Collect IP addresses from running containers.
        
        Args:
            node_configs: List of NodeConfig objects
            wait_for_ips: Whether to wait for containers to receive IPs
        """
        from ..monitoring.waiter.docker_ip_waiter import DockerIPWaiter
        
        self._node_configs = node_configs
        self._node_ips = []
        self._node_ip_map = {}
        
        # Calculate topology statistics
        self.node_count = len(node_configs)
        self.root_count = sum(1 for n in node_configs if n.role == 'root')
        self.master_count = sum(1 for n in node_configs if n.role == 'master')
        self.full_count = sum(1 for n in node_configs if n.role == 'full')
        
        # Prepare container names
        container_names = []
        for node in node_configs:
            # node.node_id is numeric (1, 2, 3, ...)
            container_names.append(f"cellframe-stage-node-{node.node_id}")
        
        # Wait for IPs if requested
        if wait_for_ips:
            ip_waiter = DockerIPWaiter(self._docker_client)
            logger.info("global_context_waiting_for_ips", 
                       containers=container_names,
                       count=len(container_names))
            
            if not ip_waiter.wait_for_container_ips(container_names, timeout=30.0):
                logger.error("global_context_ip_timeout", 
                           containers=container_names)
                raise RuntimeError(
                    f"Containers did not receive IP addresses within timeout: {container_names}"
                )
            
            # Collect IPs from waiter cache
            for node in node_configs:
                container_name = f"cellframe-stage-node-{node.node_id}"
                node_key = f"node{node.node_id}"
                
                try:
                    ip_address = ip_waiter.get_container_ip(container_name)
                    self._node_ips.append(ip_address)
                    self._node_ip_map[node_key] = ip_address
                    logger.debug("global_context_ip_resolved",
                               node=node_key,
                               container=container_name,
                               ip=ip_address)
                except RuntimeError as e:
                    logger.error("global_context_ip_error",
                               node=node_key,
                               container=container_name,
                               error=str(e))
                    raise
        else:
            # Direct IP collection without waiting
            for node in node_configs:
                container_name = f"cellframe-stage-node-{node.node_id}"
                node_key = f"node{node.node_id}"
                
                try:
                    container = self._docker_client.containers.get(container_name)
                    networks = container.attrs['NetworkSettings']['Networks']
                    ip_address = next(
                        (net['IPAddress'] for net in networks.values() 
                         if net.get('IPAddress')),
                        None
                    )
                    
                    if ip_address:
                        self._node_ips.append(ip_address)
                        self._node_ip_map[node_key] = ip_address
                        logger.debug("global_context_ip_resolved",
                                   node=node_key,
                                   ip=ip_address)
                    else:
                        logger.warning("global_context_no_ip",
                                     node=node_key,
                                     container=container_name)
                except Exception as e:
                    logger.warning("global_context_ip_collection_error",
                                 node=node_key,
                                 error=str(e))
        
        logger.info("global_context_ips_collected",
                   count=len(self._node_ips),
                   node_ip_map=self._node_ip_map)
    
    def add_extra_node_ip(self, key: str, ip: str) -> None:
        """Register an additional node (e.g. from node_compose_gen) in the IP map."""
        self._node_ip_map[key] = ip
        if ip not in self._node_ips:
            self._node_ips.append(ip)

    def refresh_ips(self) -> None:
        """Refresh IP addresses from containers (useful after restart)."""
        if self._node_configs:
            self.collect_node_ips(self._node_configs, wait_for_ips=True)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert context to dictionary for scenario variables.
        
        Returns:
            Dictionary with all global context variables
        """
        # Build node lists by role
        root_nodes = [f"node-{i+1}" for i in range(self.root_count)]
        master_nodes = [f"node-{self.root_count + i + 1}" for i in range(self.master_count)]
        full_nodes = [f"node-{self.root_count + self.master_count + i + 1}" for i in range(self.full_count)]
        all_nodes = root_nodes + master_nodes + full_nodes
        
        # Build index lists (0-based for loops)
        root_indices = list(range(1, self.root_count + 1))
        master_indices = list(range(self.root_count + 1, self.root_count + self.master_count + 1))
        full_indices = list(range(self.root_count + self.master_count + 1, self.node_count + 1))
        
        result = {
            # Network configuration
            'network_name': self.network_name,
            'topology_name': self.topology_name,
            'native_ticker': self.native_ticker,
            'node_port': self.node_port,
            
            # Node IP addresses
            'node_ips': self._node_ips,  # Array: [ip1, ip2, ip3, ...]
            'node_ip': self._node_ip_map,  # Map: {node1: ip1, node2: ip2, ...}
            
            # Topology statistics
            'node_count': self.node_count,
            'root_count': self.root_count,
            'master_count': self.master_count,
            'full_count': self.full_count,
            
            # Node lists by role (format: node-1, node-2, ...)
            # Use these for docker_op services and config: nodes
            'root_nodes': root_nodes,
            'master_nodes': master_nodes,
            'full_nodes': full_nodes,
            'all_nodes': all_nodes,
            
            # Node indices by role (for loops: 1, 2, 3, ...)
            'root_indices': root_indices,
            'master_indices': master_indices,
            'full_indices': full_indices,
            'all_indices': root_indices + master_indices + full_indices,
            
            # First/last node shortcuts
            'first_root': root_nodes[0] if root_nodes else None,
            'last_root': root_nodes[-1] if root_nodes else None,
            'first_master': master_nodes[0] if master_nodes else None,
            'last_master': master_nodes[-1] if master_nodes else None,
            
            # Seed nodes (usually root nodes)
            'seed_nodes': root_nodes,
            'validator_nodes': master_nodes,
        }
        
        # Role-based IP shortcuts: {{node_ip_root-1}}, {{node_ip_master-2}}, etc.
        for i in range(self.root_count):
            node_id = i + 1
            ip = self._node_ip_map.get(f'node{node_id}') or self._node_ip_map.get(f'node-{node_id}')
            if ip:
                result[f'node_ip_root-{i + 1}'] = ip
        for i in range(self.master_count):
            node_id = self.root_count + i + 1
            ip = self._node_ip_map.get(f'node{node_id}') or self._node_ip_map.get(f'node-{node_id}')
            if ip:
                result[f'node_ip_master-{i + 1}'] = ip
        for i in range(self.full_count):
            node_id = self.root_count + self.master_count + i + 1
            ip = self._node_ip_map.get(f'node{node_id}') or self._node_ip_map.get(f'node-{node_id}')
            if ip:
                result[f'node_ip_full-{i + 1}'] = ip
        
        return result
    
    def get_node_ip(self, node_id: str) -> Optional[str]:
        """
        Get IP address for specific node.
        
        Args:
            node_id: Node identifier (e.g., 'node1', 'node2')
            
        Returns:
            IP address or None if not found
        """
        return self._node_ip_map.get(node_id)
    
    def __repr__(self) -> str:
        return (
            f"ScenarioGlobalContext(network={self.network_name}, "
            f"topology={self.topology_name}, "
            f"nodes={self.node_count}, "
            f"ips_collected={len(self._node_ips)})"
        )

