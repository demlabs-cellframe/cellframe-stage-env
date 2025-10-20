"""
Network manager for cellframe test environment.

Manages the lifecycle of test network:
- Dynamic node creation based on topology
- Node startup/shutdown
- Network readiness checking
- Node discovery and configuration
"""

import asyncio
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel

from ..config.loader import ConfigLoader, NetworkTopology
from ..docker.compose import DockerComposeManager
from ..monitoring.health import HealthChecker, HealthStatus
from ..utils.logger import get_logger

logger = get_logger(__name__)


class NodeConfig(BaseModel):
    """Configuration for a single node."""
    
    node_id: int
    role: str  # root, master, full, validator
    node_type: str  # for grouping
    rpc_port: int
    p2p_port: int
    cf_port: int
    http_port: int
    ip_address: str


class NetworkManager:
    """Manage cellframe test network lifecycle."""
    
    def __init__(self, base_path: Path, topology_name: str = "default"):
        """
        Initialize network manager.
        
        Args:
            base_path: Base path to stage-env directory
            topology_name: Name of topology to use
        """
        self.base_path = base_path
        self.topology_name = topology_name
        
        # Load configuration
        self.config_loader = ConfigLoader(base_path)
        self.topology = self.config_loader.load_topology(topology_name)
        
        # Docker compose manager
        self.compose = DockerComposeManager(
            base_path,
            project_name="cellframe-stage"
        )
        
        # Health checker
        self.health_checker = HealthChecker()
        
        # Node configurations
        self.nodes: Dict[str, NodeConfig] = {}
        
        logger.info("network_manager_initialized",
                   topology=topology_name,
                   network=self.topology.network.name)
    
    def generate_node_configs(self) -> List[NodeConfig]:
        """
        Generate node configurations from topology.
        
        Returns:
            List of NodeConfig objects
        """
        logger.info("generating_node_configs")
        
        configs = []
        node_counter = 1
        
        # Base settings from topology
        settings = self.topology.network_settings
        
        for node_type, node_spec in self.topology.topology.items():
            for i in range(node_spec.count):
                config = NodeConfig(
                    node_id=node_counter,
                    role=node_spec.role,
                    node_type=node_type,
                    rpc_port=settings.base_rpc_port + node_counter - 1,
                    p2p_port=settings.base_p2p_port + node_counter - 1,
                    cf_port=settings.base_cf_port + node_counter - 1,
                    http_port=settings.base_http_port + node_counter - 1,
                    ip_address=self._calculate_ip(
                        settings.base_ip,
                        node_counter
                    ),
                )
                
                configs.append(config)
                self.nodes[f"node{node_counter}"] = config
                node_counter += 1
        
        logger.info("node_configs_generated", count=len(configs))
        return configs
    
    def _calculate_ip(self, base_ip: str, node_id: int) -> str:
        """
        Calculate node IP address.
        
        Args:
            base_ip: Base IP (e.g., "172.20.0.10")
            node_id: Node ID
            
        Returns:
            IP address string
        """
        parts = base_ip.split(".")
        last_octet = int(parts[3]) + node_id - 1
        return f"{parts[0]}.{parts[1]}.{parts[2]}.{last_octet}"
    
    async def start(
        self,
        rebuild: bool = False,
        wait_ready: bool = True,
    ) -> None:
        """
        Start the test network.
        
        Args:
            rebuild: Rebuild Docker images before starting
            wait_ready: Wait for all nodes to be ready
        """
        logger.info("starting_network",
                   topology=self.topology_name,
                   rebuild=rebuild)
        
        # Generate node configurations
        if not self.nodes:
            self.generate_node_configs()
        
        # Build images if requested
        if rebuild:
            logger.info("rebuilding_images")
            self.compose.build(no_cache=rebuild)
        
        # Start services
        logger.info("starting_docker_services")
        self.compose.up(detach=True, wait=False)
        
        # Wait for nodes to be ready
        if wait_ready:
            await self._wait_for_network_ready()
        
        logger.info("network_started",
                   nodes=len(self.nodes),
                   topology=self.topology.network.name)
    
    async def stop(self, remove_volumes: bool = False) -> None:
        """
        Stop the test network.
        
        Args:
            remove_volumes: Remove data volumes
        """
        logger.info("stopping_network", remove_volumes=remove_volumes)
        
        self.compose.down(volumes=remove_volumes)
        
        logger.info("network_stopped")
    
    async def restart(self, node_name: Optional[str] = None) -> None:
        """
        Restart network or specific node.
        
        Args:
            node_name: Node to restart (None = all)
        """
        if node_name:
            logger.info("restarting_node", node=node_name)
            # Restart specific container
            containers = self.compose.ps()
            for container in containers:
                service = container.labels.get("com.docker.compose.service")
                if service == node_name:
                    container.restart()
                    logger.info("node_restarted", node=node_name)
                    return
            
            logger.warning("node_not_found", node=node_name)
        else:
            logger.info("restarting_network")
            await self.stop(remove_volumes=False)
            await self.start(rebuild=False, wait_ready=True)
    
    async def get_status(self) -> Dict[str, any]:
        """
        Get network status.
        
        Returns:
            Status information dict
        """
        logger.debug("getting_network_status")
        
        # Get container status
        service_status = self.compose.get_service_status()
        
        # Get health status
        node_urls = {
            name: f"http://localhost:{config.http_port}"
            for name, config in self.nodes.items()
        }
        
        health_checks = [
            (url, node_id, "http")
            for node_id, url in node_urls.items()
        ]
        
        health_statuses = await self.health_checker.check_multiple(health_checks)
        
        return {
            "topology": self.topology_name,
            "network_name": self.topology.network.name,
            "total_nodes": len(self.nodes),
            "containers": service_status,
            "health": {s.node_id: s.dict() for s in health_statuses},
        }
    
    async def _wait_for_network_ready(self, timeout: float = 300.0) -> None:
        """
        Wait for all nodes to be ready.
        
        Args:
            timeout: Maximum wait time in seconds
        """
        logger.info("waiting_for_network_ready", timeout=timeout)
        
        # First wait for Docker containers
        self.compose.wait_for_services(timeout=int(timeout))
        
        # Then wait for HTTP endpoints
        node_urls = {
            name: f"http://localhost:{config.http_port}"
            for name, config in self.nodes.items()
        }
        
        tasks = [
            self.health_checker.wait_for_healthy(
                url,
                node_id,
                check_type="http",
                timeout=timeout,
            )
            for node_id, url in node_urls.items()
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check results
        failed_nodes = []
        for node_id, result in zip(node_urls.keys(), results):
            if isinstance(result, Exception) or not result:
                failed_nodes.append(node_id)
        
        if failed_nodes:
            logger.error("nodes_not_ready",
                        failed=failed_nodes,
                        count=len(failed_nodes))
            raise TimeoutError(f"Nodes not ready: {', '.join(failed_nodes)}")
        
        logger.info("network_ready", nodes=len(self.nodes))
    
    def get_node_logs(
        self,
        node_name: str,
        tail: int = 100,
        follow: bool = False,
    ) -> str:
        """
        Get logs for a node.
        
        Args:
            node_name: Node identifier
            tail: Number of lines from end
            follow: Follow log output
            
        Returns:
            Log output
        """
        logger.debug("fetching_logs", node=node_name, tail=tail)
        
        return self.compose.logs(node_name, follow=follow, tail=tail)
    
    def exec_in_node(
        self,
        node_name: str,
        command: List[str],
    ) -> tuple[int, str]:
        """
        Execute command in node container.
        
        Args:
            node_name: Node identifier
            command: Command to execute
            
        Returns:
            Tuple of (exit_code, output)
        """
        logger.debug("executing_in_node",
                    node=node_name,
                    command=" ".join(command))
        
        return self.compose.exec(node_name, command)
    
    def list_nodes(self) -> List[Dict[str, any]]:
        """
        List all configured nodes.
        
        Returns:
            List of node information dicts
        """
        return [
            {
                "name": name,
                "id": config.node_id,
                "role": config.role,
                "type": config.node_type,
                "rpc_port": config.rpc_port,
                "p2p_port": config.p2p_port,
                "ip": config.ip_address,
            }
            for name, config in self.nodes.items()
        ]
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        await self.health_checker.close()

