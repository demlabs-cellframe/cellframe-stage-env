"""
Configuration generator for cellframe nodes.

Generates:
- Network configuration files
- Node-specific configs
- Certificate generation coordination
"""

import shutil
from pathlib import Path
from typing import Dict, List, Optional

from ..config.loader import ConfigLoader, NetworkTopology
from ..certs.generator import CertGenerator
from ..network.models import NodeConfig
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ConfigGenerator:
    """Generate configuration files for cellframe nodes."""
    
    def __init__(self, base_path: Path, config_path: Optional[Path] = None):
        """
        Initialize config generator.
        
        Args:
            base_path: Base path to stage-env directory
            config_path: Optional path to stage-env.cfg
        """
        self.base_path = base_path
        self.config_loader = ConfigLoader(base_path, config_path)
        
        # Load paths from config
        paths_config = self.config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', 'cache')
        
        # Directories
        self.cache_dir = (base_path / cache_dir_relative).resolve()
        self.configs_cache = self.cache_dir / "configs"
        self.data_cache = self.cache_dir / "data"
        self.certs_cache = self.cache_dir / "certs"
        
        # Initialize cert generator with correct certs path
        self.cert_generator = CertGenerator(base_path, certs_dir=self.certs_cache)
        
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
        
        # Build mapping: node_id -> validator_idx (sequential: 0, 1, 2, ...)
        # Validator certificates are indexed sequentially, not by node_id!
        validator_nodes = [n for n in nodes if n.is_seed_node or n.consensus_participation]
        node_id_to_validator_idx = {n.node_id: idx for idx, n in enumerate(validator_nodes)}
        
        # Generate node-specific configs first (basic configs without chain configs)
        for node in nodes:
            validator_idx = node_id_to_validator_idx.get(node.node_id)
            self._generate_node_config(node, topology, force, validator_idx)
        
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
            
            for node in nodes:
                # Replace placeholders with node-specific values
                node_cfg_content = base_cfg_content.replace("NODE_IP_PLACEHOLDER", node.ip_address)
                
                # CRITICAL: Enable seed_mode for ROOT and MASTER nodes for genesis creation
                # ROOT nodes need seed_mode for DAG-PoA genesis events (first events without parent hashes)
                # MASTER nodes need seed_mode for ESBocs genesis block (first block without prev_block)
                # seed_mode will be disabled AFTER genesis and configs regenerated
                if node.role in ['root', 'master']:
                    node_cfg_content = node_cfg_content.replace("seed_mode=false", "seed_mode=true")
                    logger.debug("seed_mode_enabled_for_genesis", node_id=node.node_id, role=node.role)
                
                node_etc_base = self.configs_cache / f"node{node.node_id}"
                node_etc_base.mkdir(parents=True, exist_ok=True)
                base_cfg_path = node_etc_base / "cellframe-node.cfg"
                base_cfg_path.write_text(node_cfg_content)
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
        
        # Build mapping: node_id -> validator_idx (sequential: 0, 1, 2, ...)
        # Validator certificates are indexed sequentially, not by node_id!
        validator_nodes = [n for n in nodes if n.is_seed_node or n.consensus_participation]
        node_id_to_validator_idx = {n.node_id: idx for idx, n in enumerate(validator_nodes)}
        
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
            # Root nodes are just "root" - they participate only in DAG-PoA consensus
            # Master nodes are "master" - they participate only in ESBocs consensus
            node_role = node.role
            config_content = config_content.replace("NODE_ROLE_PLACEHOLDER", node_role)
            config_content = config_content.replace("SEED_NODES_PLACEHOLDER", seed_nodes_hosts)
            config_content = config_content.replace("PERMANENT_NODES_HOSTS_PLACEHOLDER", permanent_nodes_hosts)
            
            # Replace EVENTS_SIGN_CERT_PLACEHOLDER for root nodes
            # SDK loads events-sign-cert from network config, not chain config!
            # callback_created receives l_net->pub.config (network config), not chain config
            # ROOT nodes use stagenet.root.N (DAG-PoA), MASTER nodes use stagenet.master.N (ESBocs)
            if "EVENTS_SIGN_CERT_PLACEHOLDER" in config_content:
                if node.is_seed_node:  # ROOT nodes only
                    root_idx = node.node_id - 1  # ROOT nodes: 0, 1, 2
                    events_sign_cert = f"events-sign-cert=pvt.{network_name}.root.{root_idx}"
                    config_content = config_content.replace("EVENTS_SIGN_CERT_PLACEHOLDER", events_sign_cert)
                    logger.debug("events_sign_cert_set", node_id=node.node_id, cert=f"pvt.{network_name}.root.{root_idx}")
                else:
                    # Remove placeholder for non-root nodes
                    lines = config_content.split('\n')
                    filtered_lines = [line for line in lines if "EVENTS_SIGN_CERT_PLACEHOLDER" not in line]
                    config_content = '\n'.join(filtered_lines)
            
            # Replace BLOCKS_SIGN_CERT_PLACEHOLDER for master nodes
            # MASTER nodes (node4,5,6) use stagenet.master.{0,1,2} (sequential!)
            if "BLOCKS_SIGN_CERT_PLACEHOLDER" in config_content:
                if node.consensus_participation and not node.is_seed_node:  # MASTER nodes only
                    master_idx = node.node_id - 4  # node4→0, node5→1, node6→2
                    blocks_sign_cert = f"blocks-sign-cert=pvt.{network_name}.master.{master_idx}"
                    config_content = config_content.replace("BLOCKS_SIGN_CERT_PLACEHOLDER", blocks_sign_cert)
                    logger.debug("blocks_sign_cert_set", node_id=node.node_id, cert=f"pvt.{network_name}.master.{master_idx}")
                else:
                    # Remove placeholder for non-master nodes
                    lines = config_content.split('\n')
                    filtered_lines = [line for line in lines if "BLOCKS_SIGN_CERT_PLACEHOLDER" not in line]
                    config_content = '\n'.join(filtered_lines)
            
            # Write network config to /etc/network/{network_name}.cfg (Cellframe expects this!)
            dst_file = node_network_base / f"{network_name}.cfg"
            dst_file.write_text(config_content)
            
            # Generate chain configs using Jinja2 templates
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
                
                # Prepare Jinja2 context for chain configs
                chain_context = {
                    'validators_addrs': validator_addrs,
                    'root_nodes_addrs': root_nodes_addrs,
                    'auth_certs_number': auth_certs_number,
                    'auth_certs_number_verify': auth_certs_number_verify,
                    # Genesis parameters (empty initially, filled after genesis creation)
                    'static_genesis_event': '',
                    'is_static_genesis_event': 'false',
                    'static_genesis_block': '',
                    'is_static_genesis_block': 'false',
                    'fee_addr': ''
                }
                
                # Process chain config templates
                for chain_template in chains_template_dir.glob("*.cfg.j2"):
                    # Render Jinja2 template
                    from jinja2 import Template
                    template_content = chain_template.read_text()
                    template = Template(template_content)
                    chain_content = template.render(**chain_context)
                    
                    # Write to .cfg file (remove .j2 extension)
                    output_name = chain_template.stem  # Removes .j2, keeps .cfg
                    dst_chain_cfg = node_network_dir / output_name
                    dst_chain_cfg.write_text(chain_content)
                    
                    logger.debug("chain_config_rendered",
                               node_id=node.node_id,
                               chain=output_name,
                               template=chain_template.name)
                
                # Also process plain .cfg files (legacy, for backwards compatibility)
                for chain_cfg in chains_template_dir.glob("*.cfg"):
                    # Skip if corresponding .j2 exists
                    if (chains_template_dir / f"{chain_cfg.name}.j2").exists():
                        continue
                    
                    # Read and process legacy config
                    chain_content_legacy = chain_cfg.read_text()
                    chain_content_legacy = chain_content_legacy.replace("VALIDATORS_ADDRS_PLACEHOLDER", validator_addrs)
                    chain_content_legacy = chain_content_legacy.replace("AUTHORIZED_NODES_ADDRS_PLACEHOLDER", root_nodes_addrs)
                    chain_content_legacy = chain_content_legacy.replace("AUTH_CERTS_NUMBER_PLACEHOLDER", str(auth_certs_number))
                    chain_content_legacy = chain_content_legacy.replace("AUTH_CERTS_NUMBER_VERIFY_PLACEHOLDER", str(auth_certs_number_verify))
                    
                    # Write processed chain config
                    dst_chain_cfg = node_network_dir / chain_cfg.name
                    dst_chain_cfg.write_text(chain_content_legacy)
                    
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
        Collect validator addresses from generated certificates.
        
        ESBocs validators are nodes with consensus_participation=true (master nodes).
        
        Args:
            nodes: List of node configurations
            network_name: Network name
            
        Returns:
            Comma-separated list of validator addresses (for ESBocs consensus)
        """
        validator_addrs = []
        
        # Collect addresses for nodes participating in ESBocs consensus (master nodes)
        validator_nodes = [n for n in nodes if n.consensus_participation]
        
        for node in validator_nodes:
            # Validator nodes use validator_addr.txt for ESBocs consensus
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
        force: bool = False,
        validator_idx: Optional[int] = None
    ) -> None:
        """
        Generate configuration for a specific node.
        
        Args:
            node: Node configuration
            topology: Network topology
            force: Force regeneration
            validator_idx: Validator index (if node is validator)
        """
        node_id = node.node_id
        logger.debug("generating_node_config",
                    node_id=node_id,
                    role=node.role,
                    validator_idx=validator_idx)
        
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
        
        # Generate node-specific config snippet (with blocks-sign-cert if validator)
        network_name = topology.network.name
        self._generate_node_snippet(node_config_dir, node, topology, validator_idx, network_name)
        
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
        topology: NetworkTopology,
        validator_idx: Optional[int] = None,
        network_name: Optional[str] = None
    ) -> None:
        """
        Generate node-specific configuration snippet.
        
        Args:
            config_dir: Config directory
            node: Node configuration
            topology: Network topology
            validator_idx: Validator index (if node is validator)
            network_name: Network name (for blocks-sign-cert)
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
        
        # Add ESBocs blocks-sign-cert for validator nodes ONLY
        if node.consensus_participation and validator_idx is not None and network_name:
            config_content += f"""[esbocs]
# Blocks signing certificate (validator-specific)
# CRITICAL: Must use pvt. prefix (private key) for signing
blocks-sign-cert=pvt.{network_name}.master.{validator_idx}

"""
        
        # Write config
        snippet_path.write_text(config_content)
        logger.debug("generated_node_snippet",
                    node_id=node.node_id,
                    is_validator=node.consensus_participation,
                    validator_idx=validator_idx,
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
        
        # Copy ONLY PUBLIC validator certificates (WITHOUT pvt. prefix) to shared directory
        # CRITICAL: Private certificates (pvt.stagenet.master.N) should NEVER be in /share/ca!
        # Only public certificates (stagenet.master.N) for verification
        master_nodes = [n for n in nodes if n.consensus_participation and not n.is_seed_node]
        root_nodes = [n for n in nodes if n.is_seed_node]
        
        # Copy public ROOT certs (for DAG-PoA verification)
        for idx, node in enumerate(root_nodes):
            src_public_cert = self.certs_cache / f"node{node.node_id}" / f"{network_name}.root.{idx}.dcert"
            
            if src_public_cert.exists():
                dst_cert = shared_certs_dir / f"{network_name}.root.{idx}.dcert"
                shutil.copy2(src_public_cert, dst_cert)
                logger.debug("copied_public_root_cert_to_shared",
                           node_id=node.node_id,
                           cert_idx=idx,
                           dst=str(dst_cert))
            else:
                logger.warning("public_root_cert_not_found",
                             node_id=node.node_id,
                             cert_idx=idx,
                             expected=str(src_public_cert))
        
        # Copy public MASTER certs (for ESBocs verification)
        for idx, node in enumerate(master_nodes):
            src_public_cert = self.certs_cache / f"node{node.node_id}" / f"{network_name}.master.{idx}.dcert"
            
            if src_public_cert.exists():
                dst_cert = shared_certs_dir / f"{network_name}.master.{idx}.dcert"
                shutil.copy2(src_public_cert, dst_cert)
                logger.debug("copied_public_master_cert_to_shared",
                           node_id=node.node_id,
                           cert_idx=idx,
                           dst=str(dst_cert))
            else:
                logger.warning("public_master_cert_not_found",
                             node_id=node.node_id,
                             cert_idx=idx,
                             expected=str(src_public_cert))
        
        # Copy node-addr.dcert to ALL nodes FIRST (CRITICAL - must exist before node starts!)
        # This certificate is used for node identification and MUST match authorized_nodes_addrs
        for node in nodes:
            node_data_cert_dir = self.data_cache / f"node{node.node_id}" / "lib" / "ca"
            node_data_cert_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy node-addr.dcert (node identification certificate)
            src_node_cert = self.certs_cache / f"node{node.node_id}" / "node-addr.dcert"
            if src_node_cert.exists():
                dst_node_cert = node_data_cert_dir / "node-addr.dcert"
                shutil.copy2(src_node_cert, dst_node_cert)
                logger.debug("copied_node_addr_cert",
                           node_id=node.node_id,
                           dst=str(dst_node_cert))
        
        # Copy PRIVATE consensus certificates to /var/lib/ca for validator nodes
        # Each node gets ONLY its OWN PRIVATE certificate (with pvt. prefix)
        # ROOT nodes (1,2,3): pvt.stagenet.root.{0,1,2} for DAG-PoA events
        # MASTER nodes (4,5,6): pvt.stagenet.master.{0,1,2} for ESBocs blocks
        for node in nodes:
            if not (node.is_seed_node or node.consensus_participation):
                continue  # Skip FULL nodes
            
            node_data_cert_dir = self.data_cache / f"node{node.node_id}" / "lib" / "ca"
            node_data_cert_dir.mkdir(parents=True, exist_ok=True)
            
            # Determine certificate type and index
            if node.is_seed_node:  # ROOT nodes
                cert_type = "root"
                cert_idx = node.node_id - 1  # node1→0, node2→1, node3→2
            else:  # MASTER nodes
                cert_type = "master"
                cert_idx = node.node_id - 4  # node4→0, node5→1, node6→2
            
            # Copy PRIVATE certificate (keeps pvt. prefix for signing operations)
            src_cert = self.certs_cache / f"node{node.node_id}" / f"pvt.{network_name}.{cert_type}.{cert_idx}.dcert"
            if src_cert.exists():
                dst_cert = node_data_cert_dir / f"pvt.{network_name}.{cert_type}.{cert_idx}.dcert"
                shutil.copy2(src_cert, dst_cert)
                logger.debug("copied_private_consensus_cert",
                           node_id=node.node_id,
                           cert_type=cert_type,
                           cert_idx=cert_idx,
                           dst=str(dst_cert))
            else:
                logger.warning("private_consensus_cert_not_found", 
                             node_id=node.node_id,
                             expected=str(src_cert))
        
        # Copy ALL PUBLIC consensus certificates to EVERY node's /var/lib/ca
        # All nodes need all public certs for signature verification:
        # - stagenet.root.{0,1,2} for DAG-PoA event verification
        # - stagenet.master.{0,1,2} for ESBocs block verification
        for node in nodes:
            node_data_cert_dir = self.data_cache / f"node{node.node_id}" / "lib" / "ca"
            node_data_cert_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy all ROOT public certs (stagenet.root.{0,1,2})
            for root_idx in range(3):
                root_node_id = root_idx + 1
                src_pub_cert = self.certs_cache / f"node{root_node_id}" / f"{network_name}.root.{root_idx}.dcert"
                if src_pub_cert.exists():
                    dst_pub_cert = node_data_cert_dir / f"{network_name}.root.{root_idx}.dcert"
                    shutil.copy2(src_pub_cert, dst_pub_cert)
                    logger.debug("copied_public_root_cert",
                               node_id=node.node_id,
                               root_idx=root_idx,
                               dst=str(dst_pub_cert))
            
            # Copy all MASTER public certs (stagenet.master.{0,1,2})
            for master_idx in range(3):
                master_node_id = master_idx + 4
                src_pub_cert = self.certs_cache / f"node{master_node_id}" / f"{network_name}.master.{master_idx}.dcert"
                if src_pub_cert.exists():
                    dst_pub_cert = node_data_cert_dir / f"{network_name}.master.{master_idx}.dcert"
                    shutil.copy2(src_pub_cert, dst_pub_cert)
                    logger.debug("copied_public_master_cert",
                               node_id=node.node_id,
                               master_idx=master_idx,
                               dst=str(dst_pub_cert))
        
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

