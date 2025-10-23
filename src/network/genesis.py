"""
Genesis initialization for stagenet.

Handles initial setup tasks after network start:
- Creating validator stake orders
- Registering node aliases in GDB
- Setting up initial state
"""

import asyncio
from pathlib import Path
from typing import List, Dict
import docker

from ..utils.logger import get_logger
from .models import NodeConfig

logger = get_logger(__name__)


class GenesisInitializer:
    """Initialize genesis state for stagenet."""
    
    def __init__(self, base_path: Path, network_name: str = "stagenet", config_path: Path = None):
        """
        Initialize genesis initializer.
        
        Args:
            base_path: Base path to stage-env directory
            network_name: Network name (default: stagenet)
            config_path: Optional path to config file
        """
        self.base_path = base_path
        self.network_name = network_name
        self.docker_client = docker.from_env()
        # Load cache dir from config
        from ..config.loader import ConfigLoader
        config_loader = ConfigLoader(base_path, config_path)
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', 'cache')
        # Resolve cache dir relative to config file location (not base_path)
        if config_path:
            self.certs_cache = (config_path.parent / cache_dir_relative / "certs").resolve()
        else:
            self.certs_cache = (base_path / cache_dir_relative / "certs").resolve()
        
        logger.info("genesis_initializer_created", network=network_name)
    
    async def initialize(self, nodes: List[NodeConfig]) -> None:
        """
        Initialize genesis state.
        
        Creates validator orders for all validator nodes (root nodes).
        
        Args:
            nodes: List of node configurations
        """
        logger.info("starting_genesis_initialization", nodes=len(nodes))
        
        # Find root nodes (validators)
        validator_nodes = [n for n in nodes if n.is_seed_node]
        
        if not validator_nodes:
            logger.warning("no_validator_nodes_found")
            return
        
        logger.info("found_validator_nodes", count=len(validator_nodes))
        
        # Use first node to create orders (any node can do this)
        admin_node = nodes[0]
        container_name = f"cellframe-stage-node-{admin_node.node_id}"
        
        try:
            container = self.docker_client.containers.get(container_name)
        except docker.errors.NotFound:
            logger.error("admin_node_container_not_found", container=container_name)
            raise RuntimeError(f"Container {container_name} not found")
        
        # Wait a bit for node to initialize
        logger.info("waiting_for_node_initialization")
        await asyncio.sleep(5)
        
        # Root nodes will connect to each other via seed_nodes_hosts configuration
        # No need to manually add them to nodelist - standard bootstrap mechanism will handle it
        logger.info("root_nodes_will_connect_via_seed_nodes_hosts",
                   seed_nodes=len(validator_nodes))
        
        # Create validator orders for each validator node
        for node in validator_nodes:
            await self._create_validator_order(container, node)
        
        logger.info("genesis_initialization_complete", orders_created=len(validator_nodes))
    
    async def _setup_root_nodelists(self, root_nodes: List[NodeConfig]) -> None:
        """
        Setup nodelists for root nodes - each root node adds all other root nodes.
        
        Root nodes are the bootstrap/seed nodes that manage the network topology.
        They need to know about each other immediately.
        
        Args:
            root_nodes: List of root node configurations
        """
        logger.info("setting_up_root_nodelists", count=len(root_nodes))
        
        # Read all root node addresses first
        root_node_data = []
        for node in root_nodes:
            validator_addr_file = self.certs_cache / f"node{node.node_id}" / "validator_addr.txt"
            node_addr_file = self.certs_cache / f"node{node.node_id}" / "node_addr.txt"
            
            if not validator_addr_file.exists() or not node_addr_file.exists():
                logger.warning("node_addr_files_not_found",
                              node_id=node.node_id)
                continue
            
            validator_addr = validator_addr_file.read_text().strip()
            node_addr = node_addr_file.read_text().strip()
            
            root_node_data.append({
                'node': node,
                'validator_addr': validator_addr,
                'node_addr': node_addr
            })
        
        # For each root node, add all other root nodes to its nodelist
        for current in root_node_data:
            container_name = f"cellframe-stage-node-{current['node'].node_id}"
            
            try:
                container = self.docker_client.containers.get(container_name)
            except docker.errors.NotFound:
                logger.warning("root_node_container_not_found",
                              node_id=current['node'].node_id,
                              container=container_name)
                continue
            
            # Add this node itself first
            await self._add_to_nodelist(
                container,
                current['node'],
                current['node_addr'],
                current['node'].ip_address,
                current['node'].node_port,
                is_self=True
            )
            
            # Then add all other root nodes
            for other in root_node_data:
                if other['node'].node_id == current['node'].node_id:
                    continue  # Skip self (already added)
                
                await self._add_to_nodelist(
                    container,
                    current['node'],
                    other['node_addr'],
                    other['node'].ip_address,
                    other['node'].node_port,
                    is_self=False
                )
        
        logger.info("root_nodelists_setup_complete")
    
    async def _add_to_nodelist(
        self,
        container: docker.models.containers.Container,
        current_node: NodeConfig,
        target_node_addr: str,
        target_ip: str,
        target_port: int,
        is_self: bool = False
    ) -> None:
        """
        Add a node to current node's nodelist.
        
        Args:
            container: Docker container of current node
            current_node: Current node configuration
            target_node_addr: Node address to add (hex format)
            target_ip: IP address of target node
            target_port: Port of target node
            is_self: Whether adding the node itself
        """
        # Command: node add -net <net> -addr <node_addr>
        # Note: Cellframe Node uses "node add" not "nodelist add"
        cmd = [
            "cellframe-node-cli",
            "node", "add",
            "-net", self.network_name,
            "-addr", target_node_addr
        ]
        
        logger.info("adding_to_nodelist",
                   current_node_id=current_node.node_id,
                   target_addr=target_node_addr,
                   target_endpoint=f"{target_ip}:{target_port}",
                   is_self=is_self)
        
        try:
            result = container.exec_run(cmd, demux=True)
            exit_code = result.exit_code
            stdout, stderr = result.output
            
            stdout_str = stdout.decode() if stdout else ""
            stderr_str = stderr.decode() if stderr else ""
            
            if exit_code != 0:
                # Some errors are expected (e.g., node already in list)
                if "already" in stderr_str.lower() or "already" in stdout_str.lower():
                    logger.debug("node_already_in_nodelist",
                                current_node_id=current_node.node_id,
                                target_addr=target_node_addr)
                else:
                    logger.warning("nodelist_add_failed",
                                  current_node_id=current_node.node_id,
                                  target_addr=target_node_addr,
                                  exit_code=exit_code,
                                  stderr=stderr_str)
            else:
                logger.info("added_to_nodelist",
                           current_node_id=current_node.node_id,
                           target_addr=target_node_addr,
                           output=stdout_str.strip())
                
        except Exception as e:
            logger.exception("nodelist_add_exception",
                           current_node_id=current_node.node_id,
                           target_addr=target_node_addr,
                           error=str(e))
    
    async def _create_validator_order(
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
        # Certificate name for this validator (use private key)
        validator_idx = node.node_id - 1
        cert_name = f"pvt.{self.network_name}.master.{validator_idx}"
        
        # Read node address from certs cache
        node_addr_file = self.certs_cache / f"node{node.node_id}" / "validator_addr.txt"
        if not node_addr_file.exists():
            logger.error("node_addr_file_not_found",
                        node_id=node.node_id,
                        file=str(node_addr_file))
            raise FileNotFoundError(f"Node address file not found: {node_addr_file}")
        
        node_addr = node_addr_file.read_text().strip()
        logger.info("read_node_address",
                   node_id=node.node_id,
                   node_addr=node_addr)
        
        # Order parameters
        # value_min and value_max in datoshi (1 token = 10^18 datoshi)
        # For testing, use 100 tokens min, 10000 tokens max
        value_min = "100000000000000000000"  # 100 tokens
        value_max = "10000000000000000000000"  # 10000 tokens
        tax = "10.0"  # 10.0% tax (must be float с точкой)
        
        # Build CLI command
        cmd = [
            "cellframe-node-cli",
            "srv_stake", "order", "create", "validator",
            "-net", self.network_name,
            "-value_min", value_min,
            "-value_max", value_max,
            "-tax", tax,
            "-cert", cert_name,
            "-node_addr", node_addr,
            "-H", "hex"
        ]
        
        logger.info("creating_validator_order",
                   node_id=node.node_id,
                   cert=cert_name,
                   node_addr=node_addr)
        
        try:
            # Execute command in container
            result = container.exec_run(cmd, demux=True)
            exit_code = result.exit_code
            stdout, stderr = result.output
            
            stdout_str = stdout.decode() if stdout else ""
            stderr_str = stderr.decode() if stderr else ""
            
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
    
    async def register_node_aliases(self, nodes: List[NodeConfig]) -> None:
        """
        Register node aliases in GDB for node discovery.
        
        This allows nodes to find each other by validator address.
        
        Args:
            nodes: List of node configurations
        """
        logger.info("registering_node_aliases", count=len(nodes))
        
        # Use first node as admin
        admin_node = nodes[0]
        container_name = f"cellframe-stage-node-{admin_node.node_id}"
        
        try:
            container = self.docker_client.containers.get(container_name)
        except docker.errors.NotFound:
            logger.error("admin_node_container_not_found", container=container_name)
            raise RuntimeError(f"Container {container_name} not found")
        
        # Register each node
        for node in nodes:
            # Read node address
            node_addr_file = self.certs_cache / f"node{node.node_id}" / "validator_addr.txt"
            if not node_addr_file.exists():
                logger.warning("node_addr_file_not_found",
                              node_id=node.node_id)
                continue
            
            node_addr = node_addr_file.read_text().strip()
            
            # GDB command to register node_alias
            # Format: global_db set -net <net> node_alias.<node_addr> <ip:port>
            cmd = [
                "cellframe-node-cli",
                "global_db", "set",
                "-net", self.network_name,
                f"node_alias.{node_addr}",
                f"{node.ip_address}:{node.node_port}"
            ]
            
            logger.info("registering_node_alias",
                       node_id=node.node_id,
                       node_addr=node_addr,
                       endpoint=f"{node.ip_address}:{node.node_port}")
            
            try:
                result = container.exec_run(cmd, demux=True)
                exit_code = result.exit_code
                
                if exit_code != 0:
                    stdout, stderr = result.output
                    stderr_str = stderr.decode() if stderr else ""
                    logger.warning("node_alias_registration_failed",
                                  node_id=node.node_id,
                                  exit_code=exit_code,
                                  stderr=stderr_str)
                else:
                    logger.info("node_alias_registered",
                              node_id=node.node_id,
                              node_addr=node_addr)
                    
            except Exception as e:
                logger.exception("node_alias_registration_exception",
                               node_id=node.node_id,
                               error=str(e))
        
        logger.info("node_alias_registration_complete")
        
        # Bring all nodes online explicitly (in case auto_online didn't work)
        logger.info("bringing_nodes_online")
        for node in nodes:
            container_name = f"cellframe-stage-node-{node.node_id}"
            try:
                container = self.docker_client.containers.get(container_name)
                cmd = ["cellframe-node-cli", "net", "-net", self.network_name, "go", "online"]
                result = container.exec_run(cmd, demux=True)
                
                if result.exit_code == 0:
                    logger.info("node_brought_online", node_id=node.node_id)
                else:
                    stdout, stderr = result.output
                    stderr_str = stderr.decode() if stderr else ""
                    logger.warning("failed_to_bring_node_online",
                                  node_id=node.node_id,
                                  stderr=stderr_str)
            except Exception as e:
                logger.warning("exception_bringing_node_online",
                              node_id=node.node_id,
                              error=str(e))

