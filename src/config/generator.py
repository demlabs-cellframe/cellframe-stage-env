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

from jinja2 import Template

from ..config.manager import get_config_loader
from ..config.loader import NetworkTopology
from ..certs.generator import CertGenerator
from ..network.models import NodeConfig
from src.utils.logger import get_logger

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
        self.config_loader = get_config_loader()
        
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
        
        # Generate base cellframe-node.cfg for each node first using Jinja2
        base_cfg_template = self.templates_dir / "base" / "cellframe-node.cfg.j2"
        if base_cfg_template.exists():
            template_content = base_cfg_template.read_text()
            template = Template(template_content)
            
            for node in nodes:
                # CRITICAL: Initial seed_mode configuration for node startup
                # ALL nodes start with seed_mode=false by default
                # Actual seed_mode management is done EXPLICITLY via YAML scenarios
                # 
                # Default Configuration:
                # - ALL nodes (ROOT, MASTER, FULL): seed_mode=false
                #
                # YAML Scenario Management (see scenarios/genesis/):
                # - PHASE 1 (phase1_zerochain.yml):
                #   * Explicitly enable_seed_mode on ROOT nodes in setup section
                #   * Create genesis event (token_decl) in seed mode
                #   * Explicitly disable_seed_mode on ROOT nodes with zerochain_genesis_hash
                #   * Restart nodes
                #   * Regular operations (emission, funding) with seed_mode=false
                #
                # - PHASE 2 (phase2_esbocs.yml):
                #   * Delegate keys on zerochain (seed_mode=false)
                #   * Explicitly enable_seed_mode on MASTER nodes
                #   * Create genesis block (first mainchain transaction) in seed mode
                #   * Explicitly disable_seed_mode on MASTER nodes with main_genesis_hash
                #   * Final restart with ESBocs active
                #
                # This approach provides full transparency and control over seed_mode lifecycle
                seed_mode = 'false'  # All nodes start with seed_mode=false
                
                # Render template with node-specific context
                context = {
                    'node_ip': node.ip_address,
                    'seed_mode': seed_mode
                }
                node_cfg_content = template.render(**context)
                
                logger.debug("initial_seed_mode_false_for_all_nodes", 
                           node_id=node.node_id,
                           role=node.role,
                           note="seed_mode will be explicitly managed by YAML scenarios")
                
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
            src_network_cfg = self.templates_dir / "stagenet.cfg.j2"
            
        if not src_network_cfg.exists():
            logger.warning("network_config_template_not_found",
                         network=network_name,
                         path=str(src_network_cfg))
            return
        
        logger.debug("network_config_source", path=str(src_network_cfg))
        
        # Read template content and prepare for Jinja2 rendering
        template_content = src_network_cfg.read_text()
        network_template = Template(template_content)
        
        # Prepare network-wide variables
        # Collect seed nodes (root nodes) and permanent nodes (masters)
        root_nodes = [n for n in nodes if n.role == 'root']
        master_nodes = [n for n in nodes if n.role == 'master']
        
        # Format as arrays in DAP config format: param=[value1,value2,value3]
        # Based on dap_config.c:237 - dap_strsplit(l_val, ",", -1)
        # Array must be ONE line starting with [ and ending with ]
        # Format: IP:PORT where PORT is configurable via topology (default 8079)
        # CRITICAL: Both seed_nodes_aliases AND seed_nodes_hosts are required!
        # This matches tests-in-docker configuration for proper node discovery
        if root_nodes:
            hosts_list = ','.join([f"{n.ip_address}:{n.node_port}" for n in root_nodes])
            seed_nodes_hosts = f"[{hosts_list}]"
            # Aliases use certificate names: network.root.N
            aliases_list = ','.join([f"{network_name}.root.{idx}" for idx in range(len(root_nodes))])
            seed_nodes_aliases = f"[{aliases_list}]"
        else:
            seed_nodes_hosts = "[]"
            seed_nodes_aliases = "[]"
        
        # Permanent nodes hosts - only root nodes (network infrastructure)
        if root_nodes:
            hosts_list = ','.join([f"{n.ip_address}:{n.node_port}" for n in root_nodes])
            permanent_nodes_hosts = f"[{hosts_list}]"
        else:
            permanent_nodes_hosts = "[]"
        
        # Build mapping: node_id -> validator_idx (sequential: 0, 1, 2, ...)
        # Validator certificates are indexed sequentially, not by node_id!
        validator_nodes = [n for n in nodes if n.is_seed_node or n.consensus_participation]
        node_id_to_validator_idx = {n.node_id: idx for idx, n in enumerate(validator_nodes)}
        
        # Prepare chain configs context (shared for all nodes)
        # Chain configs are generated per-node but share common context
        chains_template_dir = self.templates_dir / "chains"
        base_chain_context = None
        chain_templates = {}
        
        if chains_template_dir.exists():
            # Collect validator addresses (only for zerochain - mainchain uses PoS without explicit validators list)
            validator_addrs = self._collect_validator_addresses(nodes, network_name)
            root_nodes_addrs = self._collect_root_node_addresses(nodes, network_name)
            
            # Collect MASTER node addresses for mainchain ESBocs validators
            # CRITICAL: Mainchain ESBocs requires validators_addrs for initialization
            # Even though we use PoS, SDK still checks validators_addrs if min_validators_count > 0
            # We collect MASTER nodes (consensus_participation but not seed_node) as validators
            master_validator_nodes = [n for n in nodes if n.consensus_participation and not n.is_seed_node]
            master_validator_addrs = self._collect_validator_addresses(master_validator_nodes, network_name) if master_validator_nodes else "[]"
            
            # CRITICAL: If no master validators yet (first phase), we still need min_validators_count
            # for genesis block creation, but validators_addrs can be empty (will be filled in PHASE 2)
            # SDK will allow initialization with min_validators_count > 0 if validators_addrs is empty
            # only if genesis_mode=true, but genesis_mode should be false for root nodes
            # CRITICAL: Always use master validator addresses in mainchain validators_addrs
            # Even in Phase 1 when master nodes are not yet started, we pre-configure their addresses
            # This satisfies SDK validation requirement: validators_addrs must contain >= min_validators_count addresses
            # When master nodes start in Phase 2, they will already be configured as validators
            master_validators_count = len(master_validator_nodes)
            
            if master_validators_count > 0:
                # Master nodes exist - use their addresses
                mainchain_min_validators_count = max(2, master_validators_count // 2 + 1)  # 2/3 consensus
                logger.info("mainchain_validators_configured",
                           master_validators_count=master_validators_count,
                           min_validators_count=mainchain_min_validators_count,
                           note="Using master node addresses in validators_addrs for mainchain")
            else:
                # No master nodes configured - this should not happen in normal flow
                # But if it does, use root nodes as fallback
                logger.warning("no_master_nodes_configured_using_root_fallback",
                             note="No master nodes found - using root nodes as fallback validators")
                master_validator_addrs = root_nodes_addrs
                root_nodes_count_for_fallback = len([n for n in nodes if n.is_seed_node])
                mainchain_min_validators_count = max(1, root_nodes_count_for_fallback // 2 + 1)
            
            # Calculate consensus parameters
            root_nodes_count = len([n for n in nodes if n.is_seed_node])
            auth_certs_number = root_nodes_count
            auth_certs_number_verify = max(1, root_nodes_count // 2 + 1)
            
            # Get minimum_fee from config (default 0.1 for production, can be overridden in config)
            stage_config = self.config_loader.load_stage_config()
            minimum_fee = stage_config.get('minimum_fee', '0.1')
            
            # Prepare base chain context (shared for all nodes)
            # CRITICAL: genesis_mode, static_genesis_event, fee_addr will be set per-node
            base_chain_context = {
                'validators_addrs': validator_addrs,  # Used for zerochain (all validators: root + master)
                'mainchain_validators_addrs': master_validator_addrs,  # Used for mainchain (master node addresses)
                'root_nodes_addrs': root_nodes_addrs,
                'auth_certs_number': auth_certs_number,
                'auth_certs_number_verify': auth_certs_number_verify,
                'static_genesis_event': '',  # Will be set per-node after genesis event creation
                'is_static_genesis_event': 'false',  # Will be set per-node after genesis event creation
                'static_genesis_block': '',  # Will be set per-node after genesis block creation
                'is_static_genesis_block': 'false',  # Will be set per-node after genesis block creation
                'fee_addr': '',  # Will be set per-node after fee wallet creation
                'min_validators_count': mainchain_min_validators_count,  # Set to 2 for 2/3 consensus
                'poa_mode': 'true',  # CRITICAL: Always use PoA mode (validators specified in config)
                'minimum_fee': str(minimum_fee)  # Default from config (0.1), can be changed by scenario
            }
            
            # Load chain templates ONCE (shared for all nodes)
            for chain_template in chains_template_dir.glob("*.cfg.j2"):
                chain_template_content = chain_template.read_text()
                chain_templates[chain_template.stem] = Template(chain_template_content)
        
        # Generate network config for each node using Jinja2
        # Cellframe Node expects:
        # 1. /etc/{cellframe-node,network}.cfg - main configs  
        # 2. /etc/network/{network_name}.cfg - network config file
        # 3. /etc/network/{network_name}/ - directory for chain configs
        for node in nodes:
            node_etc_base = self.configs_cache / f"node{node.node_id}"
            node_network_base = node_etc_base / "network"
            node_network_dir = node_network_base / network_name
            node_network_dir.mkdir(parents=True, exist_ok=True)
            
            # Prepare node-specific context for Jinja2
            node_role = node.role  # 'root', 'master', or 'full'
            
            # Calculate certificate indices for ROOT and MASTER nodes
            events_sign_cert = None
            blocks_sign_cert = None
            
            if node.is_seed_node:  # ROOT nodes
                root_idx = node.node_id - 1  # node1→0, node2→1, node3→2
                events_sign_cert = f"pvt.{network_name}.root.{root_idx}"
                logger.debug("events_sign_cert_prepared", node_id=node.node_id, cert=events_sign_cert)
            
            if node.consensus_participation and not node.is_seed_node:  # MASTER nodes
                master_idx = node.node_id - 4  # node4→0, node5→1, node6→2
                blocks_sign_cert = f"pvt.{network_name}.master.{master_idx}"
                logger.debug("blocks_sign_cert_prepared", node_id=node.node_id, cert=blocks_sign_cert)
            
            # Render template with node-specific context
            network_context = {
                'node_role': node_role,
                'seed_nodes_aliases': seed_nodes_aliases,  # Required for node discovery
                'seed_nodes_hosts': seed_nodes_hosts,
                'permanent_nodes_hosts': permanent_nodes_hosts,  # Root nodes only
                'events_sign_cert': events_sign_cert,
                'blocks_sign_cert': blocks_sign_cert
            }
            config_content = network_template.render(**network_context)
            
            # Write network config to /etc/network/{network_name}.cfg (Cellframe expects this!)
            dst_file = node_network_base / f"{network_name}.cfg"
            dst_file.write_text(config_content)
            
            logger.debug("network_config_written",
                        node_id=node.node_id,
                        path=str(dst_file),
                        first_line=config_content.split('\n')[0] if config_content else "EMPTY",
                        has_general_section="[general]" in config_content)
            
            # Generate chain configs INDIVIDUALLY for each node with node-specific settings
            if base_chain_context and chain_templates:
                node_chains_dir = node_network_base / network_name
                node_chains_dir.mkdir(parents=True, exist_ok=True)
                
                # CRITICAL: genesis_mode setting per node type
                # ROOT nodes: genesis_mode=false (they don't create genesis block, only MASTER nodes do)
                # MASTER nodes: genesis_mode=true (they create genesis block)
                if node.is_seed_node:  # ROOT nodes
                    node_genesis_mode = 'false'  # ROOT nodes don't create genesis block
                elif node.consensus_participation and not node.is_seed_node:  # MASTER nodes
                    node_genesis_mode = 'true'  # MASTER nodes create genesis block
                else:  # FULL nodes
                    node_genesis_mode = 'false'  # FULL nodes don't participate in consensus
                
                # Prepare node-specific chain context
                node_chain_context = base_chain_context.copy()
                node_chain_context['genesis_mode'] = node_genesis_mode
                
                # Render chain configs for this node
                for chain_name, chain_template in chain_templates.items():
                    chain_content = chain_template.render(**node_chain_context)
                    dst_chain_cfg = node_chains_dir / chain_name
                    dst_chain_cfg.write_text(chain_content)
                    
                    logger.debug("chain_config_written_per_node",
                               node_id=node.node_id,
                               node_role=node.role,
                               chain=chain_name,
                               genesis_mode=node_genesis_mode,
                               path=str(dst_chain_cfg),
                               has_jinja_tags="{{ " in chain_content)
            
            logger.debug("network_config_generated",
                       node_id=node.node_id,
                       role=node.role,
                       network=network_name,
                       dst=str(dst_file))
    
    def regenerate_chain_configs_with_custom_validators(
        self,
        nodes: List[NodeConfig],
        network_name: str,
        custom_validators_addrs: str,
        min_validators_count: Optional[int] = None,
        static_genesis_event: Optional[str] = None,
        fee_addr: Optional[str] = None
    ) -> None:
        """
        Regenerate chain configs with custom validators_addrs override.
        
        NOTE: This is primarily used for zerochain configuration.
        Mainchain uses PoS and does NOT require validators_addrs in config.
        
        Args:
            nodes: List of all nodes (for root_nodes_addrs calculation)
            network_name: Network name
            custom_validators_addrs: Custom validators addresses in format "[addr1,addr2]" (only used for zerochain)
            min_validators_count: Optional override for min_validators_count (auto-calculated if None)
            static_genesis_event: Optional static_genesis_event to preserve
            fee_addr: Optional fee_addr to preserve
        """
        logger.info("regenerating_chain_configs_with_custom_validators",
                   network=network_name,
                   nodes=len(nodes),
                   custom_validators=custom_validators_addrs[:50] + "..." if len(custom_validators_addrs) > 50 else custom_validators_addrs,
                   min_validators_count=min_validators_count)
        
        # Collect root node addresses
        root_nodes_addrs = self._collect_root_node_addresses(nodes, network_name)
        
        # Calculate consensus parameters
        root_nodes_count = len([n for n in nodes if n.is_seed_node])
        auth_certs_number = root_nodes_count
        auth_certs_number_verify = max(1, root_nodes_count // 2 + 1)
        
        # Calculate min_validators_count based on custom_validators_addrs
        # CRITICAL: min_validators_count must NOT be greater than actual validators count
        # Otherwise SDK returns -2: "l_node_addrs_count < l_validators_count"
        if min_validators_count is None:
            # Auto-calculate from validators_addrs count
            # Extract addresses from format "[addr1,addr2,addr3]"
            validators_list = custom_validators_addrs.strip('[]').split(',')
            validators_list = [v.strip() for v in validators_list if v.strip()]
            calculated_min_validators = len(validators_list)
            logger.debug("auto_calculated_min_validators_count",
                        validators_count=calculated_min_validators,
                        validators_list_preview=validators_list[:3])
        else:
            calculated_min_validators = min_validators_count
        
        # Prepare Jinja2 context with custom validators_addrs
        chain_context = {
            'validators_addrs': custom_validators_addrs,  # For zerochain compatibility
            'mainchain_validators_addrs': custom_validators_addrs,  # CRITICAL: For main.cfg.j2 template
            'min_validators_count': calculated_min_validators,  # CRITICAL: must match validators count
            'poa_mode': 'true',  # CRITICAL: PoA mode when validators are specified
            'root_nodes_addrs': root_nodes_addrs,
            'auth_certs_number': auth_certs_number,
            'auth_certs_number_verify': auth_certs_number_verify,
            'static_genesis_event': static_genesis_event if static_genesis_event else '',
            'is_static_genesis_event': 'true' if static_genesis_event else 'false',
            'static_genesis_block': '',
            'is_static_genesis_block': 'false',
            'fee_addr': fee_addr if fee_addr else '',  # CRITICAL: Preserve fee_addr!
            'genesis_mode': 'true'
        }
        
        # Log what we're preserving
        if static_genesis_event:
            logger.info("preserving_static_genesis_event_in_regeneration",
                      hash=static_genesis_event[:16],
                      note="static_genesis_event will be preserved in regenerated configs")
        if fee_addr:
            logger.info("preserving_fee_addr_in_regeneration",
                      fee_addr=fee_addr[:16],
                      note="fee_addr will be preserved in regenerated configs")
        
        # Render all chain templates
        chains_template_dir = self.templates_dir / "chains"
        if not chains_template_dir.exists():
            raise RuntimeError(f"Chain templates directory not found: {chains_template_dir}")
        
        rendered_chain_configs = {}
        for chain_template in chains_template_dir.glob("*.cfg.j2"):
            chain_template_content = chain_template.read_text()
            template = Template(chain_template_content)
            chain_content = template.render(**chain_context)
            output_name = chain_template.stem  # main.cfg, zerochain.cfg
            rendered_chain_configs[output_name] = chain_content
            
            # Debug: check if static_genesis_event is in rendered content
            if output_name == 'zerochain.cfg' and static_genesis_event:
                if static_genesis_event in chain_content:
                    logger.info("static_genesis_event_verified_in_rendered_config",
                              hash=static_genesis_event[:16],
                              chain=output_name,
                              note="static_genesis_event found in rendered zerochain config")
                else:
                    logger.error("static_genesis_event_missing_in_rendered_config",
                               hash=static_genesis_event[:16],
                               chain=output_name,
                               content_preview=chain_content[:500],
                               note="CRITICAL: static_genesis_event not found in rendered config!")
            
            logger.debug("chain_config_rendered",
                       chain=output_name,
                       validators=custom_validators_addrs[:30])
        
        # Write chain configs for ALL nodes
        for node in nodes:
            node_network_base = self.configs_cache / f"node{node.node_id}" / "network"
            node_chains_dir = node_network_base / network_name
            node_chains_dir.mkdir(parents=True, exist_ok=True)
            
            # Write all rendered chain configs
            for chain_name, chain_content in rendered_chain_configs.items():
                dst_chain_cfg = node_chains_dir / chain_name
                dst_chain_cfg.write_text(chain_content)
                logger.debug("chain_config_written",
                           node_id=node.node_id,
                           chain=chain_name,
                           path=str(dst_chain_cfg))
        
        logger.info("chain_configs_regenerated_with_custom_validators",
                   nodes=len(nodes),
                   chains=len(rendered_chain_configs))
    
    def update_minimum_fee(
        self,
        nodes: List[NodeConfig],
        network_name: str,
        minimum_fee: str
    ) -> None:
        """
        Update minimum_fee in main chain configs for all nodes.
        
        This is used to:
        1. Set minimum_fee=0 before genesis block creation (allow first tx without fee)
        2. Set minimum_fee=0.1 after genesis block is finalized (enforce fees)
        
        Args:
            nodes: List of all nodes
            network_name: Network name (e.g., 'stagenet')
            minimum_fee: New minimum_fee value (e.g., '0' or '0.1')
        """
        logger.info("updating_minimum_fee",
                   network=network_name,
                   nodes=len(nodes),
                   minimum_fee=minimum_fee)
        
        chains_template_dir = self.templates_dir / "chains"
        if not chains_template_dir.exists():
            logger.warning("chains_template_dir_not_found", path=str(chains_template_dir))
            return
        
        # Load main.cfg.j2 template
        main_cfg_template_path = chains_template_dir / "main.cfg.j2"
        if not main_cfg_template_path.exists():
            logger.warning("main_cfg_template_not_found", path=str(main_cfg_template_path))
            return
        
        template_content = main_cfg_template_path.read_text()
        main_template = Template(template_content)
        
        # Update minimum_fee for each node
        for node in nodes:
            node_chains_dir = self.configs_cache / f"node{node.node_id}" / "network" / network_name
            main_cfg_path = node_chains_dir / "main.cfg"
            
            if not main_cfg_path.exists():
                logger.warning("main_cfg_not_found_for_node",
                             node_id=node.node_id,
                             path=str(main_cfg_path))
                continue
            
            # Read current config to preserve other settings
            current_content = main_cfg_path.read_text()
            
            # Parse current settings (simple regex-based extraction)
            import re
            
            # Extract current values to preserve them
            context = {'minimum_fee': minimum_fee}
            
            # Extract validators_addrs, min_validators_count, etc. from current config
            for key in ['validators_addrs', 'min_validators_count', 'poa_mode', 'fee_addr', 
                       'static_genesis_block', 'is_static_genesis_block', 'genesis_mode']:
                match = re.search(rf'^{key}\s*=\s*(.+?)$', current_content, re.MULTILINE)
                if match:
                    context[key] = match.group(1).strip()
            
            # Also need to get mainchain_validators_addrs if it's in the template
            match = re.search(r'validators_addrs\s*=\s*(.+?)$', current_content, re.MULTILINE)
            if match:
                context['mainchain_validators_addrs'] = match.group(1).strip()
                context['validators_addrs'] = match.group(1).strip()
            
            # Render template with updated minimum_fee
            try:
                updated_content = main_template.render(**context)
                main_cfg_path.write_text(updated_content)
                logger.debug("updated_minimum_fee_for_node",
                           node_id=node.node_id,
                           minimum_fee=minimum_fee)
            except Exception as e:
                logger.error("failed_to_update_minimum_fee",
                           node_id=node.node_id,
                           error=str(e))
        
        logger.info("minimum_fee_updated_for_all_nodes",
                   nodes=len(nodes),
                   minimum_fee=minimum_fee)
    
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
        
        # Add ESBocs blocks-sign-cert for MASTER nodes ONLY (not ROOT nodes)
        # CRITICAL: Only MASTER nodes (4,5,6) participate in ESBocs consensus
        # ROOT nodes (1,2,3) use DAG-PoA for zerochain, not ESBocs
        if node.consensus_participation and not node.is_seed_node and network_name:
            # MASTER nodes: node4→master.0, node5→master.1, node6→master.2
            master_idx = node.node_id - 4
            config_content += f"""[esbocs]
# Blocks signing certificate (validator-specific)
# CRITICAL: Must use pvt. prefix (private key) for signing
blocks-sign-cert=pvt.{network_name}.master.{master_idx}

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
            
            # SPECIAL CASE: root-1 (node1) receives ALL private certificates for centralized genesis
            # This allows testing threshold consensus (2/3) with all signatures from single node
            if node.node_id == 1 and node.is_seed_node:
                logger.info("copying_all_private_certs_to_root1_for_centralized_genesis")
                all_pvt_certs_copied = 0
                
                # Copy all ROOT private certificates (pvt.stagenet.root.{0,1,2})
                for root_idx in range(3):
                    root_node_id = root_idx + 1
                    if root_node_id == node.node_id:
                        # Skip own certificate (already copied above)
                        continue
                    
                    src_pvt_cert = self.certs_cache / f"node{root_node_id}" / f"pvt.{network_name}.root.{root_idx}.dcert"
                    if src_pvt_cert.exists():
                        dst_pvt_cert = node_data_cert_dir / f"pvt.{network_name}.root.{root_idx}.dcert"
                        shutil.copy2(src_pvt_cert, dst_pvt_cert)
                        all_pvt_certs_copied += 1
                        logger.debug("copied_private_root_cert_to_root1",
                                   root_idx=root_idx,
                                   dst=str(dst_pvt_cert))
                    else:
                        logger.warning("private_root_cert_not_found_for_root1",
                                     root_idx=root_idx,
                                     expected_path=str(src_pvt_cert))
                
                logger.info("all_private_certs_copied_to_root1",
                           own_cert=1,
                           additional_certs=all_pvt_certs_copied,
                           total_pvt_certs=all_pvt_certs_copied + 1,
                           note="root-1 can now perform centralized genesis with threshold consensus")
        
        # Copy ALL PUBLIC consensus certificates to EVERY node's /var/lib/ca
        # All nodes need all public certs for signature verification:
        # - stagenet.root.{0,1,2} for DAG-PoA event verification
        # - stagenet.master.{0,1,2} for ESBocs block verification
        logger.info("distributing_public_certs_to_all_nodes", 
                   total_nodes=len(nodes), 
                   network=network_name)
        
        for node in nodes:
            node_data_cert_dir = self.data_cache / f"node{node.node_id}" / "lib" / "ca"
            node_data_cert_dir.mkdir(parents=True, exist_ok=True)
            
            root_certs_copied = 0
            master_certs_copied = 0
            
            # Copy all ROOT public certs (stagenet.root.{0,1,2})
            for root_idx in range(3):
                root_node_id = root_idx + 1
                src_pub_cert = self.certs_cache / f"node{root_node_id}" / f"{network_name}.root.{root_idx}.dcert"
                if src_pub_cert.exists():
                    dst_pub_cert = node_data_cert_dir / f"{network_name}.root.{root_idx}.dcert"
                    shutil.copy2(src_pub_cert, dst_pub_cert)
                    root_certs_copied += 1
                    logger.debug("copied_public_root_cert",
                               node_id=node.node_id,
                               root_idx=root_idx,
                               dst=str(dst_pub_cert))
                else:
                    logger.warning("public_root_cert_not_found",
                                 node_id=node.node_id,
                                 root_idx=root_idx,
                                 expected_path=str(src_pub_cert))
            
            # Copy all MASTER public certs (stagenet.master.{0,1,2})
            for master_idx in range(3):
                master_node_id = master_idx + 4
                src_pub_cert = self.certs_cache / f"node{master_node_id}" / f"{network_name}.master.{master_idx}.dcert"
                if src_pub_cert.exists():
                    dst_pub_cert = node_data_cert_dir / f"{network_name}.master.{master_idx}.dcert"
                    shutil.copy2(src_pub_cert, dst_pub_cert)
                    master_certs_copied += 1
                    logger.debug("copied_public_master_cert",
                               node_id=node.node_id,
                               master_idx=master_idx,
                               dst=str(dst_pub_cert))
                else:
                    logger.warning("public_master_cert_not_found",
                                 node_id=node.node_id,
                                 master_idx=master_idx,
                                 expected_path=str(src_pub_cert))
            
            logger.info("public_certs_distributed_to_node",
                       node_id=node.node_id,
                       root_certs=root_certs_copied,
                       master_certs=master_certs_copied)
        
        logger.info("certificates_generated", count=node_count)
    
    def clean(self, clean_certs: bool = False) -> None:
        """
        Clean generated configurations.
        
        Args:
            clean_certs: Also clean certificates
        """
        logger.info("cleaning_configs", clean_certs=clean_certs)
        
        # Clean config cache (safe to use shutil.rmtree - configs are not root-owned)
        if self.configs_cache.exists():
            shutil.rmtree(self.configs_cache)
            logger.debug("cleaned_configs")
        
        # Clean data cache using Docker (handles root-owned files from containers)
        if self.data_cache.exists():
            try:
                import docker
                docker_client = docker.from_env()
                logger.debug("cleaning_data_cache_with_docker", path=str(self.data_cache))
                # Use Docker container to remove files (handles root-owned files)
                docker_client.containers.run(
                    image="alpine:latest",
                    command=["sh", "-c", "rm -rf /cleanup/data && echo 'Data cache cleaned'"],
                    volumes={
                        str(self.cache_dir.absolute()): {
                            'bind': '/cleanup',
                            'mode': 'rw'
                        }
                    },
                    remove=True,
                    detach=False,
                )
                logger.debug("cleaned_data_with_docker")
            except (ImportError, docker.errors.DockerException) as e:
                # Fallback to shutil.rmtree if Docker is not available
                logger.warning("docker_unavailable_fallback_to_shutil",
                             error=str(e),
                             note="Data cache may contain root-owned files that cannot be removed")
                try:
                    shutil.rmtree(self.data_cache)
                    logger.debug("cleaned_data_with_shutil")
                except PermissionError as pe:
                    logger.error("failed_to_clean_data_cache",
                               error=str(pe),
                               note="Files may be owned by root. Install Docker or use sudo.")
                    raise
        
        # Clean certificates if requested (safe to use shutil.rmtree - certs are not root-owned)
        if clean_certs and self.certs_cache.exists():
            shutil.rmtree(self.certs_cache)
            logger.debug("cleaned_certificates")
        
        logger.info("configs_cleaned")

