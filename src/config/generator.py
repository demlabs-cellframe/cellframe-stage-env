"""
Configuration generator for cellframe nodes.

Generates:
- Network configuration files
- Node-specific configs
- Certificate generation coordination
"""

import shutil
from pathlib import Path
from typing import Dict, List

from ..config.loader import ConfigLoader, NetworkTopology
from ..certs.generator import CertGenerator
from ..network.models import NodeConfig
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ConfigGenerator:
    """Generate configuration files for cellframe nodes."""
    
    def __init__(self, base_path: Path):
        """
        Initialize config generator.
        
        Args:
            base_path: Base path to stage-env directory
        """
        self.base_path = base_path
        self.config_loader = ConfigLoader(base_path)
        self.cert_generator = CertGenerator(base_path)
        
        # Directories
        self.cache_dir = base_path / "cache"
        self.configs_cache = self.cache_dir / "configs"
        self.data_cache = self.cache_dir / "data"
        self.certs_cache = self.cache_dir / "certs"
        
        # Template directories
        self.templates_dir = base_path / "config" / "templates"
        
        logger.debug("config_generator_initialized", base_path=str(base_path))
    
    def generate_all(
        self,
        topology: NetworkTopology,
        nodes: List[NodeConfig],
        force: bool = False
    ) -> None:
        """
        Generate all configurations and certificates.
        
        Args:
            topology: Network topology
            nodes: List of node configurations
            force: Force regeneration even if exists
        """
        logger.info("generating_configurations",
                   network=topology.network.name,
                   nodes=len(nodes),
                   force=force)
        
        # Ensure cache directories exist
        self._ensure_directories()
        
        # Generate network config files for all nodes
        self._generate_network_configs(topology, nodes)
        
        # Generate node-specific configs
        for node in nodes:
            self._generate_node_config(node, topology, force)
        
        # Generate certificates
        self._generate_certificates(nodes, topology, force)
        
        logger.info("configurations_generated",
                   network=topology.network.name,
                   nodes=len(nodes))
    
    def _ensure_directories(self) -> None:
        """Ensure all required cache directories exist."""
        dirs = [
            self.cache_dir,
            self.configs_cache,
            self.data_cache,
            self.certs_cache,
        ]
        
        for directory in dirs:
            directory.mkdir(parents=True, exist_ok=True)
    
    def _generate_network_configs(self, topology: NetworkTopology, nodes: List[NodeConfig]) -> None:
        """
        Generate network configuration files.
        
        Args:
            topology: Network topology
            nodes: List of nodes to generate configs for
        """
        logger.debug("generating_network_configs", network=topology.network.name)
        
        network_name = topology.network.name
        
        # Source template for network config
        src_network_cfg = self.templates_dir / f"{network_name}.cfg"
        
        if not src_network_cfg.exists():
            # Try with 'stagenet' as fallback
            src_network_cfg = self.templates_dir / "stagenet.cfg"
            
        if not src_network_cfg.exists():
            logger.warning("network_config_template_not_found",
                         network=network_name,
                         path=str(src_network_cfg))
            return
        
        logger.debug("network_config_source", path=str(src_network_cfg))
        
        # Read template content
        template_content = src_network_cfg.read_text()
        
        # Prepare network-wide variables
        # Collect seed nodes (root nodes) and permanent nodes (masters)
        root_nodes = [n for n in nodes if n.role == 'root']
        master_nodes = [n for n in nodes if n.role == 'master']
        
        seed_nodes_hosts = ','.join([n.ip_address for n in root_nodes])
        permanent_nodes_hosts = ','.join([n.ip_address for n in master_nodes])
        permanent_nodes_addrs = ','.join([f"{n.ip_address}:{n.p2p_port}" for n in master_nodes])
        
        # Generate network config for each node
        # Cellframe Node expects:
        # 1. /etc/network/{network_name}.cfg - main network config file
        # 2. /etc/network/{network_name}/ - directory for chain configs
        for node in nodes:
            node_network_base = self.configs_cache / f"node{node.node_id}" / "network"
            node_network_dir = node_network_base / network_name
            node_network_dir.mkdir(parents=True, exist_ok=True)
            
            # Replace placeholders with node-specific values
            config_content = template_content
            config_content = config_content.replace("NODE_ROLE_PLACEHOLDER", node.role)
            config_content = config_content.replace("SEED_NODES_PLACEHOLDER", seed_nodes_hosts)
            config_content = config_content.replace("PERMANENT_NODES_HOSTS_PLACEHOLDER", permanent_nodes_hosts)
            config_content = config_content.replace("PERMANENT_NODES_ADDRS_PLACEHOLDER", permanent_nodes_addrs)
            
            # Write network config to /etc/network/{network_name}.cfg (Cellframe expects this!)
            dst_file = node_network_base / f"{network_name}.cfg"
            dst_file.write_text(config_content)
            
            # Copy chain configs to /etc/network/{network_name}/ directory
            chains_template_dir = self.templates_dir / "chains"
            if chains_template_dir.exists():
                for chain_cfg in chains_template_dir.glob("*.cfg"):
                    dst_chain_cfg = node_network_dir / chain_cfg.name
                    shutil.copy2(chain_cfg, dst_chain_cfg)
                    logger.debug("chain_config_copied",
                               node_id=node.node_id,
                               chain=chain_cfg.name)
            
            logger.debug("network_config_generated",
                       node_id=node.node_id,
                       role=node.role,
                       network=network_name,
                       dst=str(dst_file))
    
    def _generate_node_config(
        self,
        node: NodeConfig,
        topology: NetworkTopology,
        force: bool = False
    ) -> None:
        """
        Generate configuration for a specific node.
        
        Args:
            node: Node configuration
            topology: Network topology
            force: Force regeneration
        """
        node_id = node.node_id
        logger.debug("generating_node_config",
                    node_id=node_id,
                    role=node.role)
        
        # Node-specific directories
        node_config_dir = self.configs_cache / f"node{node_id}" / "cellframe-node.cfg.d"
        node_network_dir = self.configs_cache / f"node{node_id}" / "network"
        node_data_dir = self.data_cache / f"node{node_id}"
        
        # Create directories
        node_config_dir.mkdir(parents=True, exist_ok=True)
        node_network_dir.mkdir(parents=True, exist_ok=True)
        node_data_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy base config snippets
        self._copy_base_configs(node_config_dir)
        
        # Network config is generated by _generate_network_configs()
        # No need to copy it here
        
        # Generate node-specific config snippet
        self._generate_node_snippet(node_config_dir, node, topology)
        
        logger.debug("node_config_generated",
                    node_id=node_id,
                    config_dir=str(node_config_dir))
    
    def _copy_base_configs(self, dest_dir: Path) -> None:
        """
        Copy all base configuration snippets from templates.
        
        Args:
            dest_dir: Destination directory for configs
        """
        # Copy all .cfg files from cellframe-node.cfg.d directory
        src_dir = self.templates_dir / "cellframe-node.cfg.d"
        if src_dir.exists():
            for cfg_file in src_dir.glob("*.cfg"):
                dst = dest_dir / cfg_file.name
                if not dst.exists():
                    shutil.copy2(cfg_file, dst)
                    logger.debug("copied_config", src=cfg_file.name, dst=str(dst))
        else:
            logger.warning("base_configs_dir_not_found", dir=str(src_dir))
    
    def _generate_node_snippet(
        self,
        config_dir: Path,
        node: NodeConfig,
        topology: NetworkTopology
    ) -> None:
        """
        Generate node-specific configuration snippet.
        
        Args:
            config_dir: Config directory
            node: Node configuration
            topology: Network topology
        """
        snippet_path = config_dir / f"node{node.node_id}.cfg"
        
        # Generate config content
        config_content = f"""# Node {node.node_id} configuration
# Role: {node.role}
# Type: {node.node_type}

[general]
# Node identification
node_id={node.node_id}
node_role={node.role}

[server]
# Network ports
enabled=true
listen_address=[0.0.0.0:{node.cf_port}]

[http]
# HTTP/JSON-RPC interface  
enabled=true
listen_address=[0.0.0.0:{node.http_port}]

[dag]
# DAG settings
events_sign_cert=node-{node.node_id}-cert

"""
        
        # Write config
        snippet_path.write_text(config_content)
        logger.debug("generated_node_snippet",
                    node_id=node.node_id,
                    path=str(snippet_path))
    
    def _generate_certificates(
        self,
        nodes: List[NodeConfig],
        topology: NetworkTopology,
        force: bool = False
    ) -> None:
        """
        Generate certificates for all nodes using cf-cert-generator utility.
        
        Args:
            nodes: List of node configurations
            topology: Network topology
            force: Force regeneration
        """
        logger.info("generating_certificates",
                   count=len(nodes),
                   force=force)
        
        network_name = topology.network.name
        node_count = len(nodes)
        
        # Check if certificates already exist (using standard node-addr name)
        first_node_cert = self.data_cache / "node1" / "lib" / "ca" / "node-addr.dcert"
        
        if not force and first_node_cert.exists():
            logger.info("certificates_already_exist", count=node_count)
            return
        
        # Generate all certificates using cf-cert-generator
        # This creates files in temporary certs_dir: nodeX/{network}-nodeX.dcert
        result = self.cert_generator.generate_all(
            network_name=network_name,
            node_count=node_count,
            validator_count=min(3, node_count)  # Use min 3 validators
        )
        
        # Copy generated certificates to data/lib/ca directories for each node
        import shutil
        for node_idx in range(1, node_count + 1):
            node_data_cert_dir = self.data_cache / f"node{node_idx}" / "lib" / "ca"
            node_data_cert_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy main node certificate (standard name: node-addr.dcert)
            src_node_cert = self.certs_cache / f"node{node_idx}" / "node-addr.dcert"
            dst_node_cert = node_data_cert_dir / "node-addr.dcert"
            
            if src_node_cert.exists():
                shutil.copy2(src_node_cert, dst_node_cert)
                logger.debug("copied_node_cert",
                           node_id=node_idx,
                           src=str(src_node_cert),
                           dst=str(dst_node_cert))
            else:
                logger.warning("node_cert_not_found",
                             node_id=node_idx,
                             expected=str(src_node_cert))
            
            # Copy validator certificate if exists (ESBocs consensus)
            # ESBOCS expects certificates named: {network}.master.{index}
            # Example: stagenet.master.0, stagenet.master.1, etc.
            validator_idx = node_idx - 1
            src_validator_cert = self.certs_cache / f"node{node_idx}" / f"{network_name}.master.{validator_idx}.dcert"
            if src_validator_cert.exists():
                dst_validator_cert = node_data_cert_dir / f"{network_name}.master.{validator_idx}.dcert"
                shutil.copy2(src_validator_cert, dst_validator_cert)
                logger.debug("copied_validator_cert",
                           node_id=node_idx,
                           validator_idx=validator_idx,
                           src=str(src_validator_cert),
                           dst=str(dst_validator_cert))
        
        logger.info("certificates_generated", count=node_count)
    
    def clean(self, clean_certs: bool = False) -> None:
        """
        Clean generated configurations.
        
        Args:
            clean_certs: Also clean certificates
        """
        logger.info("cleaning_configs", clean_certs=clean_certs)
        
        # Clean config cache
        if self.configs_cache.exists():
            shutil.rmtree(self.configs_cache)
            logger.debug("cleaned_configs")
        
        # Clean data cache
        if self.data_cache.exists():
            shutil.rmtree(self.data_cache)
            logger.debug("cleaned_data")
        
        # Clean certificates if requested
        if clean_certs and self.certs_cache.exists():
            shutil.rmtree(self.certs_cache)
            logger.debug("cleaned_certificates")
        
        logger.info("configs_cleaned")

