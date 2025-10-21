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
        
        # Generate node-specific configs first (basic configs without chain configs)
        for node in nodes:
            self._generate_node_config(node, topology, force)
        
        # Generate certificates (creates validator_addr.txt files)
        self._generate_certificates(nodes, topology, force)
        
        # Generate network config files for all nodes (requires validator addresses)
        self._generate_network_configs(topology, nodes)
        
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
        
        # Generate base cellframe-node.cfg for each node first
        base_cfg_template = self.templates_dir / "base" / "cellframe-node.cfg.template"
        if base_cfg_template.exists():
            base_cfg_content = base_cfg_template.read_text()
            # Enable HTTP server by default for testing (TODO: make configurable via topology/scenario)
            http_enabled = "true"
            base_cfg_content = base_cfg_content.replace("HTTP_SERVER_ENABLED_PLACEHOLDER", http_enabled)
            
            for node in nodes:
                node_etc_base = self.configs_cache / f"node{node.node_id}"
                node_etc_base.mkdir(parents=True, exist_ok=True)
                base_cfg_path = node_etc_base / "cellframe-node.cfg"
                base_cfg_path.write_text(base_cfg_content)
                logger.debug("base_config_generated", node_id=node.node_id)
                
                # Copy config snippets from cellframe-node.cfg.d templates
                cfg_d_template_dir = self.templates_dir / "cellframe-node.cfg.d"
                if cfg_d_template_dir.exists():
                    node_cfg_d = node_etc_base / "cellframe-node.cfg.d"
                    node_cfg_d.mkdir(parents=True, exist_ok=True)
                    
                    for cfg_snippet in cfg_d_template_dir.glob("*.cfg"):
                        dst_snippet = node_cfg_d / cfg_snippet.name
                        shutil.copy2(cfg_snippet, dst_snippet)
                        logger.debug("config_snippet_copied",
                                   node_id=node.node_id,
                                   snippet=cfg_snippet.name)
        
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
        
        # Format as arrays in DAP config format: param=[value1,value2,value3]
        # Based on dap_config.c:237 - dap_strsplit(l_val, ",", -1)
        # Array must be ONE line starting with [ and ending with ]
        # Format: IP:PORT where PORT is configurable via topology (default 8079)
        if root_nodes:
            hosts_list = ','.join([f"{n.ip_address}:{n.node_port}" for n in root_nodes])
            seed_nodes_hosts = f"[{hosts_list}]"
        else:
            seed_nodes_hosts = "[]"
            
        if master_nodes:
            hosts_list = ','.join([f"{n.ip_address}:{n.node_port}" for n in master_nodes])
            permanent_nodes_hosts = f"[{hosts_list}]"
        else:
            permanent_nodes_hosts = "[]"
        
        # Generate network config for each node
        # Cellframe Node expects:
        # 1. /etc/{cellframe-node,network}.cfg - main configs  
        # 2. /etc/network/{network_name}.cfg - network config file
        # 3. /etc/network/{network_name}/ - directory for chain configs
        for node in nodes:
            node_etc_base = self.configs_cache / f"node{node.node_id}"
            node_network_base = node_etc_base / "network"
            node_network_dir = node_network_base / network_name
            node_network_dir.mkdir(parents=True, exist_ok=True)
            
            # Replace placeholders with node-specific values
            config_content = template_content
            config_content = config_content.replace("NODE_ROLE_PLACEHOLDER", node.role)
            config_content = config_content.replace("SEED_NODES_PLACEHOLDER", seed_nodes_hosts)
            config_content = config_content.replace("PERMANENT_NODES_HOSTS_PLACEHOLDER", permanent_nodes_hosts)
            
            # Add blocks-sign-cert to network config (only for root/seed nodes)
            if node.is_seed_node and node.node_id <= len(nodes):
                validator_idx = node.node_id - 1
                blocks_sign_cert = f"blocks-sign-cert={network_name}.master.{validator_idx}"
                config_content = config_content.replace("BLOCKS_SIGN_CERT_PLACEHOLDER", blocks_sign_cert)
            else:
                # Remove placeholder line for non-validators
                lines = config_content.split('\n')
                filtered_lines = [line for line in lines if "BLOCKS_SIGN_CERT_PLACEHOLDER" not in line]
                config_content = '\n'.join(filtered_lines)
            
            # Write network config to /etc/network/{network_name}.cfg (Cellframe expects this!)
            dst_file = node_network_base / f"{network_name}.cfg"
            dst_file.write_text(config_content)
            
            # Copy chain configs to /etc/network/{network_name}/ directory
            chains_template_dir = self.templates_dir / "chains"
            if chains_template_dir.exists():
                # Collect validator addresses from certificates (for ESBocs consensus)
                validator_addrs = self._collect_validator_addresses(nodes, network_name)
                
                # Collect root node addresses from certificates (for zerochain authorized_nodes_addrs)
                root_nodes_addrs = self._collect_root_node_addresses(nodes, network_name)
                
                # Calculate auth_certs_number for dag-poa consensus
                root_nodes_count = len([n for n in nodes if n.is_seed_node])
                auth_certs_number = root_nodes_count
                auth_certs_number_verify = max(1, root_nodes_count // 2 + 1)  # N/2 + 1
                
                for chain_cfg in chains_template_dir.glob("*.cfg"):
                    # Read template
                    chain_content = chain_cfg.read_text()
                    
                    # Replace VALIDATORS_ADDRS_PLACEHOLDER if present (for ESBocs consensus)
                    if "VALIDATORS_ADDRS_PLACEHOLDER" in chain_content:
                        chain_content = chain_content.replace(
                            "VALIDATORS_ADDRS_PLACEHOLDER",
                            validator_addrs
                        )
                    
                    # Replace AUTHORIZED_NODES_ADDRS_PLACEHOLDER if present (for zerochain DAG-PoA)
                    if "AUTHORIZED_NODES_ADDRS_PLACEHOLDER" in chain_content:
                        chain_content = chain_content.replace(
                            "AUTHORIZED_NODES_ADDRS_PLACEHOLDER",
                            root_nodes_addrs
                        )
                    
                    # Replace AUTH_CERTS_NUMBER_PLACEHOLDER (for dag-poa)
                    if "AUTH_CERTS_NUMBER_PLACEHOLDER" in chain_content:
                        chain_content = chain_content.replace(
                            "AUTH_CERTS_NUMBER_PLACEHOLDER",
                            str(auth_certs_number)
                        )
                    
                    # Replace AUTH_CERTS_NUMBER_VERIFY_PLACEHOLDER (for dag-poa)
                    if "AUTH_CERTS_NUMBER_VERIFY_PLACEHOLDER" in chain_content:
                        chain_content = chain_content.replace(
                            "AUTH_CERTS_NUMBER_VERIFY_PLACEHOLDER",
                            str(auth_certs_number_verify)
                        )
                    
                    # Write processed chain config
                    dst_chain_cfg = node_network_dir / chain_cfg.name
                    dst_chain_cfg.write_text(chain_content)
                    
                    logger.debug("chain_config_copied",
                               node_id=node.node_id,
                               chain=chain_cfg.name,
                               validators=validator_addrs if "VALIDATORS_ADDRS_PLACEHOLDER" in chain_cfg.read_text() else "N/A",
                               root_nodes=root_nodes_addrs if "AUTHORIZED_NODES_ADDRS_PLACEHOLDER" in chain_cfg.read_text() else "N/A")
            
            logger.debug("network_config_generated",
                       node_id=node.node_id,
                       role=node.role,
                       network=network_name,
                       dst=str(dst_file))
    
    def _collect_validator_addresses(
        self,
        nodes: List[NodeConfig],
        network_name: str
    ) -> str:
        """
        Collect validator addresses from generated certificates (only for root/seed nodes).
        
        Args:
            nodes: List of node configurations
            network_name: Network name
            
        Returns:
            Comma-separated list of validator addresses (for ESBocs consensus)
        """
        validator_addrs = []
        
        # Only collect addresses for root (seed) nodes - they are the validators
        root_nodes = [n for n in nodes if n.is_seed_node]
        
        for node in root_nodes:
            # Root nodes use validator_addr.txt for ESBocs consensus
            addr_file = self.certs_cache / f"node{node.node_id}" / "validator_addr.txt"
            
            if addr_file.exists():
                try:
                    addr = addr_file.read_text().strip()
                    if addr:
                        validator_addrs.append(addr)
                        logger.debug("collected_validator_addr",
                                   node_id=node.node_id,
                                   address=addr)
                except Exception as e:
                    logger.warning("failed_to_read_validator_addr",
                                 node_id=node.node_id,
                                 error=str(e))
        
        result = f"[{','.join(validator_addrs)}]"
        logger.info("validator_addresses_collected",
                   count=len(validator_addrs),
                   addresses=result[:50] + "..." if len(result) > 50 else result)
        
        return result
    
    def _collect_root_node_addresses(
        self,
        nodes: List[NodeConfig],
        network_name: str
    ) -> str:
        """
        Collect root node addresses from generated certificates for zerochain authorized_nodes_addrs.
        
        Args:
            nodes: List of node configurations
            network_name: Network name
            
        Returns:
            Comma-separated list of root node addresses (for zerochain authorized nodes)
        """
        root_addrs = []
        
        # Only collect addresses for root (seed) nodes
        root_nodes = [n for n in nodes if n.is_seed_node]
        
        for node in root_nodes:
            # Root nodes use node_addr.txt (not validator_addr.txt)
            addr_file = self.certs_cache / f"node{node.node_id}" / "node_addr.txt"
            
            if addr_file.exists():
                try:
                    addr = addr_file.read_text().strip()
                    if addr:
                        root_addrs.append(addr)
                        logger.debug("collected_root_node_addr",
                                   node_id=node.node_id,
                                   address=addr)
                except Exception as e:
                    logger.warning("failed_to_read_root_node_addr",
                                 node_id=node.node_id,
                                 error=str(e))
        
        result = f"[{','.join(root_addrs)}]"
        logger.info("root_node_addresses_collected",
                   count=len(root_addrs),
                   addresses=result[:50] + "..." if len(result) > 50 else result)
        
        return result
    
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
        # Note: [server] section removed - port configuration handled by enable-server.cfg
        # to avoid conflicts and use single port 8079 for all communications
        config_content = f"""# Node {node.node_id} configuration
# Role: {node.role}
# Type: {node.node_type}

[general]
# Node identification
node_id={node.node_id}
node_role={node.role}

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
        first_node_addr = self.certs_cache / "node1" / "node_addr.txt"
        
        if not force and first_node_cert.exists() and first_node_addr.exists():
            logger.info("certificates_already_exist", count=node_count)
            return
        
        # Generate all certificates using cf-cert-generator
        # This creates files in temporary certs_dir: nodeX/{network}-nodeX.dcert
        # Note: force flag handled by ConfigGenerator level, cert_generator always regenerates
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
            
        # Organize validator certificates according to ESBocs requirements:
        # 1. Public certificates (stagenet.master.N) → /opt/cellframe-node/share/ca (mounted, shared for all)
        # 2. Private certificates (pvt.stagenet.master.N) → copied to /opt/cellframe-node/var/lib/ca at runtime
        # Note: ESBocs uses auth_certs_prefix=stagenet.master in chain config
        logger.info("organizing_validator_certificates")
        
        # Create shared public certificates directory (will be mounted to all containers)
        shared_certs_dir = self.configs_cache / "shared" / "ca"
        shared_certs_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy validator certificates (FULL, with private keys) to shared directory
        # All nodes need to see all validator certs for consensus
        # Each node will also have its OWN cert in /var/lib/ca which takes priority
        for val_node_idx in range(1, node_count + 1):
            validator_idx = val_node_idx - 1
            # Use PRIVATE cert (full version with private key) as source
            src_private_cert = self.certs_cache / f"node{val_node_idx}" / f"pvt.{network_name}.master.{validator_idx}.dcert"
            
            if src_private_cert.exists():
                dst_cert = shared_certs_dir / f"{network_name}.master.{validator_idx}.dcert"
                # Copy full cert to shared directory
                shutil.copy2(src_private_cert, dst_cert)
                logger.debug("copied_validator_cert_to_shared",
                           validator_idx=validator_idx,
                           dst=str(dst_cert))
        
        # Copy ONLY OWN validator certificate to each ROOT node's /var/lib/ca (with private key)
        # Only root/seed nodes are validators and need their validator certificates
        # Other nodes will load validator certs from /share/ca (for verification only)
        root_nodes = [n for n in nodes if n.is_seed_node]
        for node in root_nodes:
            node_data_cert_dir = self.data_cache / f"node{node.node_id}" / "lib" / "ca"
            node_data_cert_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy only this node's own validator certificate (full version with private key)
            validator_idx = node.node_id - 1
            src_cert = self.certs_cache / f"node{node.node_id}" / f"pvt.{network_name}.master.{validator_idx}.dcert"
            if src_cert.exists():
                dst_cert = node_data_cert_dir / f"{network_name}.master.{validator_idx}.dcert"
                shutil.copy2(src_cert, dst_cert)
                logger.debug("copied_own_validator_cert",
                           node_id=node.node_id,
                           validator_idx=validator_idx,
                           dst=str(dst_cert))
        
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

