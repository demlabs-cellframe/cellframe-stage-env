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
from ..docker.compose import CLEANUP_IMAGE, CLEANUP_MOUNT_PATH, CLEANUP_CMD_TEMPLATE
from ..network.models import NodeConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ConfigGenerator:
    """Generate configuration files for cellframe nodes."""
    
    def __init__(self, base_path: Path, config_path: Optional[Path] = None, version_dir: Optional[str] = None):
        """
        Initialize config generator.
        
        Args:
            base_path: Base path to stage-env directory
            config_path: Optional path to stage-env.cfg
            version_dir: Node version directory (e.g. "v5.7", "v5.8", "v6.x") for versioned templates.
                         If None, read from [build] genesis_version in stage-env config, fallback "stable".
        """
        self.base_path = base_path
        self.config_loader = get_config_loader()

        if version_dir is None:
            stage_config = self.config_loader.load_stage_config()
            version_dir = stage_config.get('genesis_version', 'stable')
        self.version_dir = version_dir
        
        # Load paths from config
        paths_config = self.config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', 'cache')
        self.node_var_subdirs = [
            s.strip() for s in paths_config.get(
                'node_var_subdirs',
                'log, lib/ca, lib/global_db, lib/wallet, lib/network'
            ).split(',')
        ]
        
        # Directories
        self.cache_dir = (base_path / cache_dir_relative).resolve()
        self.configs_cache = self.cache_dir / "configs"
        self.data_cache = self.cache_dir / "data"
        self.certs_cache = self.cache_dir / "certs"
        
        # Derive dap-sdk branch from genesis_version (v5.8 -> release-5.8)
        sdk_branch = self._sdk_branch_from_version(version_dir)

        # Initialize cert generator with correct certs path
        self.cert_generator = CertGenerator(base_path, certs_dir=self.certs_cache,
                                            dap_sdk_branch=sdk_branch)
        
        # Template directories: versioned first, then common fallback
        self.templates_dir = base_path / "config" / "templates"
        self.versioned_templates_dir = self.templates_dir / version_dir
        
        logger.debug("config_generator_initialized", base_path=str(base_path), version_dir=version_dir)
    
    @staticmethod
    def _sdk_branch_from_version(version_dir: str) -> str:
        """Map genesis version directory (e.g. 'v5.8') to dap-sdk git branch."""
        if version_dir and version_dir.startswith("v"):
            suffix = version_dir[1:]
            if suffix.endswith(".x"):
                suffix = suffix[:-2] + ".0"
            return f"release-{suffix}"
        return "release-5.8"

    def _resolve_template(self, relative_path: str) -> Optional[Path]:
        """Find template file/dir: versioned directory first, then common fallback."""
        versioned = self.versioned_templates_dir / relative_path
        if versioned.exists():
            return versioned
        common = self.templates_dir / relative_path
        if common.exists():
            return common
        return None
    
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
        
        # Generate base cellframe-node.cfg using versioned template (v5.x/v6.x)
        base_cfg_template = self._resolve_template("cellframe-node.cfg.j2")
        if base_cfg_template:
            template_content = base_cfg_template.read_text()
            template = Template(template_content)
            logger.info("using_base_template", path=str(base_cfg_template), version=self.version_dir)
            
            for node in nodes:
                context = {
                    'node_ip': node.ip_address,
                    'seed_mode': 'true' if node.is_seed_node else 'false',
                }
                logger.info("generating_cellframe_node_cfg", 
                           node_id=node.node_id, 
                           node_ip=node.ip_address)
                node_cfg_content = template.render(**context)
                
                node_etc_base = self.configs_cache / f"node{node.node_id}"
                node_etc_base.mkdir(parents=True, exist_ok=True)
                base_cfg_path = node_etc_base / "cellframe-node.cfg"
                base_cfg_path.write_text(node_cfg_content)
                logger.debug("base_config_generated", node_id=node.node_id)
                
                # Copy config snippets from cellframe-node.cfg.d templates (versioned -> common)
                cfg_d_template_dir = self.versioned_templates_dir / "cellframe-node.cfg.d"
                if not cfg_d_template_dir.exists():
                    cfg_d_template_dir = self.templates_dir / "cellframe-node.cfg.d"
                if cfg_d_template_dir.exists():
                    node_cfg_d = node_etc_base / "cellframe-node.cfg.d"
                    node_cfg_d.mkdir(parents=True, exist_ok=True)
                    
                    snippet_context = {'network_name': network_name}
                    for cfg_snippet in cfg_d_template_dir.glob("*.cfg"):
                        dst_snippet = node_cfg_d / cfg_snippet.name
                        snippet_content = cfg_snippet.read_text()
                        if '{{' in snippet_content or '{%' in snippet_content:
                            rendered = Template(snippet_content).render(**snippet_context)
                            dst_snippet.write_text(rendered)
                        else:
                            shutil.copy2(cfg_snippet, dst_snippet)
                        logger.debug("config_snippet_copied",
                                   node_id=node.node_id,
                                   snippet=cfg_snippet.name)
                    
                    self._generate_plugins_config(node_cfg_d, node)
        
        # Source template for network config (versioned -> common fallback)
        src_network_cfg = self._resolve_template(f"{network_name}.cfg")
        if not src_network_cfg:
            src_network_cfg = self._resolve_template(f"{network_name}.cfg.j2")
        if not src_network_cfg:
            src_network_cfg = self._resolve_template("network.cfg.j2")
        if not src_network_cfg:
            logger.warning("network_config_template_not_found", network=network_name)
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
        # CRITICAL: Only ROOT nodes can be seed nodes (entry points for the network)
        # From docs: "only root nodes can serve for this purpose"
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
        chains_template_dir = self._resolve_template("chains")
        base_chain_context = None
        chain_templates = {}
        
        if chains_template_dir:
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
                mainchain_min_validators_count = max(1, master_validators_count // 2 + 1)  # 2/3 consensus
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
            # All parameters are configurable via topology.consensus section
            base_chain_context = {
                # Validator addresses
                'validators_addrs': validator_addrs,  # Used for zerochain (all validators: root + master)
                'mainchain_validators_addrs': master_validator_addrs,  # Used for mainchain (master node addresses)
                'root_nodes_addrs': root_nodes_addrs,
                # DAG-PoA parameters (zerochain)
                'auth_certs_number': auth_certs_number,
                'auth_certs_number_verify': auth_certs_number_verify,
                # Genesis hashes (filled dynamically)
                'static_genesis_event': '',  # Will be set per-node after genesis event creation
                'is_static_genesis_event': 'false',  # Will be set per-node after genesis event creation
                'static_genesis_block': '',  # Will be set per-node after genesis block creation
                'is_static_genesis_block': 'false',  # Will be set per-node after genesis block creation
                'fee_addr': '',  # Will be set per-node after fee wallet creation
                # ESBocs consensus parameters (from topology.consensus)
                'min_validators_count': mainchain_min_validators_count,  # Calculated from master_nodes_count
                'poa_mode': 'false',  # PoS mode: validators auto-delegated as stake keys (poa_mode=true is bugged in SDK)
                # Auto-generate auth_certs_prefix from network_name if not specified
                'auth_certs_prefix': topology.consensus.auth_certs_prefix or f"{network_name}.master",
                'new_round_delay': topology.consensus.new_round_delay,
                'collecting_level': topology.consensus.collecting_level,
                # Additional timing parameters (from topology.consensus)
                'round_start_sync_timeout': getattr(topology.consensus, 'round_start_sync_timeout', 5),
                'round_attempts_max': getattr(topology.consensus, 'round_attempts_max', 2),
                'round_attempt_timeout': getattr(topology.consensus, 'round_attempt_timeout', 5),
                'consensus_debug': 'true' if getattr(topology.consensus, 'consensus_debug', True) else 'false',
                # Fee parameters
                'minimum_fee': str(minimum_fee),  # Default from config (0.1), can be changed by scenario
                # Network identity
                'network_name': network_name,
                'network_id': topology.network.network_id,
                'native_ticker': getattr(topology.network, 'native_ticker', 'TCELL'),
                # Network settings
                'node_port': topology.network_settings.node_port,
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
                # Certificate format: stagenet.root.pvt.0 (not pvt.stagenet.root.0!)
                root_idx = node.node_id - 1  # node1→0, node2→1
                events_sign_cert = f"{network_name}.root.pvt.{root_idx}"
                logger.debug("events_sign_cert_prepared", node_id=node.node_id, cert=events_sign_cert)
            
            if node.consensus_participation and not node.is_seed_node:  # MASTER nodes
                # master_idx: first_master_node_id→0, second→1, etc.
                # Certificate format: stagenet.master.pvt.0 (not pvt.stagenet.master.0!)
                # Use root_nodes_count instead of hardcoded value
                master_idx = node.node_id - root_nodes_count - 1
                blocks_sign_cert = f"{network_name}.master.pvt.{master_idx}"
                logger.debug("blocks_sign_cert_prepared", node_id=node.node_id, master_idx=master_idx, root_count=root_nodes_count, cert=blocks_sign_cert)
            
            # Render template with node-specific context
            network_context = {
                'network_name': network_name,
                'network_id': base_chain_context['network_id'] if base_chain_context else '0x0000000000001234',
                'native_ticker': base_chain_context['native_ticker'] if base_chain_context else 'TCELL',
                'collecting_level': base_chain_context['collecting_level'] if base_chain_context else 10.0,
                'node_role': node_role,
                'seed_nodes_aliases': seed_nodes_aliases,
                'seed_nodes_hosts': seed_nodes_hosts,
                'permanent_nodes_hosts': permanent_nodes_hosts,
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
            'poa_mode': 'false',  # PoS mode: validators auto-delegated as stake keys (poa_mode=true is bugged in SDK)
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
        
        # Render all chain templates (versioned -> common fallback)
        chains_template_dir = self._resolve_template("chains")
        if not chains_template_dir:
            raise RuntimeError(f"Chain templates directory not found in {self.versioned_templates_dir} or {self.templates_dir}")
        
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
        
        chains_template_dir = self._resolve_template("chains")
        if not chains_template_dir:
            logger.warning("chains_template_dir_not_found")
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
            # Try primary path first, then fallback to cert_generator's default path
            addr_file = self.certs_cache / f"node{node.node_id}" / "node_addr.txt"
            
            # Fallback: cert_generator may use base_path/cache/certs if config not loaded correctly
            if not addr_file.exists():
                fallback_file = self.base_path / "cache" / "certs" / f"node{node.node_id}" / "node_addr.txt"
                if fallback_file.exists():
                    logger.debug("using_fallback_cert_path",
                               node_id=node.node_id,
                               primary=str(addr_file),
                               fallback=str(fallback_file))
                    addr_file = fallback_file
            
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
        
        node_config_dir.mkdir(parents=True, exist_ok=True)
        node_network_dir.mkdir(parents=True, exist_ok=True)
        for subdir in self.node_var_subdirs:
            (node_data_dir / subdir).mkdir(parents=True, exist_ok=True)
        
        # Copy base config snippets (skips disable-plugins.cfg, handled separately)
        self._copy_base_configs(node_config_dir)
        
        # Generate per-node plugins.cfg based on [plugins] config
        self._generate_plugins_config(node_config_dir, node)
        
        # Network config is generated by _generate_network_configs()
        # No need to copy it here
        
        # Generate node-specific config snippet (with blocks-sign-cert if validator)
        network_name = topology.network.name
        self._generate_node_snippet(node_config_dir, node, topology, validator_idx, network_name)
        
        logger.debug("node_config_generated",
                    node_id=node_id,
                    config_dir=str(node_config_dir))
    
    def _copy_base_configs(self, dest_dir: Path) -> None:
        """Copy all base configuration snippets from templates (versioned -> common)."""
        src_dir = self._resolve_template("cellframe-node.cfg.d")
        if src_dir:
            for cfg_file in src_dir.glob("*.cfg"):
                dst = dest_dir / cfg_file.name
                if not dst.exists():
                    shutil.copy2(cfg_file, dst)
                    logger.debug("copied_config", src=cfg_file.name, dst=str(dst))
        else:
            logger.warning("base_configs_dir_not_found", dir=str(src_dir))
    
    def _generate_plugins_config(self, config_dir: Path, node: 'NodeConfig') -> None:
        """Generate per-node plugins.cfg based on [plugins] config section."""
        from src.config.manager import get_config_loader
        try:
            plugins_cfg = get_config_loader().get_plugins_config()
        except Exception as exc:
            logger.warning("plugins_config_load_failed",
                           error=str(exc), node_id=node.node_id)
            plugins_cfg = {'enabled': False, 'enabled_roles': [], 'enabled_nodes': []}
        
        enabled = plugins_cfg['enabled']
        if not enabled and plugins_cfg['enabled_roles']:
            enabled = node.role in plugins_cfg['enabled_roles']
        if not enabled and plugins_cfg['enabled_nodes']:
            enabled = node.node_id in plugins_cfg['enabled_nodes']
        
        plugins_file = config_dir / "plugins.cfg"
        plugins_file.write_text(
            f"[plugins]\nenabled={'true' if enabled else 'false'}\n"
        )
        logger.info("plugins_config_generated",
                    node_id=node.node_id, role=node.role, enabled=enabled,
                    plugins_cfg=plugins_cfg, path=str(plugins_file))
    
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
        # CRITICAL: Only MASTER nodes participate in ESBocs consensus
        # ROOT nodes use DAG-PoA for zerochain, not ESBocs
        if node.consensus_participation and not node.is_seed_node and network_name:
            # Calculate master_idx based on actual root_nodes_count from topology dict
            root_node_cfg = topology.topology.get('root', None)
            root_nodes_count = root_node_cfg.count if root_node_cfg else 0
            master_idx = node.node_id - root_nodes_count - 1
            # Format: stagenet.master.pvt.0 (matches certificate file names)
            config_content += f"""[esbocs]
# Blocks signing certificate (validator-specific)
# Certificate format: {network_name}.master.pvt.N
blocks-sign-cert={network_name}.master.pvt.{master_idx}

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
        Generate certificates for all nodes using cf-cert-generator Docker image.
        
        Generates certificates BEFORE container startup:
        1. Uses Docker-based cf-cert-generator for proper DAP SDK crypto
        2. Copies public certificates to shared/ca (mounted to /share/ca)
        3. Copies private certificates to each node's data/nodeN/lib/ca
        
        Args:
            nodes: List of node configurations
            topology: Network topology
            force: Force regeneration even if certificates exist
        """
        network_name = topology.network.name
        node_count = len(nodes)
        
        # ROOT nodes are seed nodes (DAG-PoA on zerochain)
        root_count = len([n for n in nodes if n.is_seed_node])
        
        logger.info("generating_certificates_with_docker",
                   network=network_name,
                   count=node_count,
                   root_count=root_count)
        
        # Check if ALL required certificates exist (not just any cert)
        certs_complete = self.cert_generator.certs_exist(
            node_count=node_count,
            root_count=root_count,
            network_name=network_name
        )
        
        if certs_complete and not force:
            logger.info("certificates_already_exist_skipping_generation")
        else:
            if force or not certs_complete:
                # Clean incomplete certs before regeneration
                self.cert_generator.clean()
            
            self.cert_generator.generate_all(
                network_name=network_name,
                node_count=node_count,
                root_count=root_count,
                network_id=topology.network.network_id
            )
            
            # Validate generated certificates
            missing = self.cert_generator._get_missing_certs(node_count, root_count, network_name)
            if missing:
                logger.error("certificate_generation_incomplete", missing=missing)
                raise RuntimeError(f"Certificate generation incomplete. Missing: {missing[:5]}")
        
        # Always copy certificates to ensure they're in place
        # (data directories may have been cleaned while certs remain)
        shared_certs_dir = self.configs_cache / "shared" / "ca"
        self.cert_generator.copy_certs_to_shared_ca(shared_certs_dir, network_name)
        
        self.cert_generator.copy_private_certs_to_node_data(
            self.data_cache,
            node_count,
            network_name
        )
        
        # Validate certificates were copied to data directories
        self._validate_certs_in_data_dirs(node_count, root_count, network_name)
        
        logger.info("certificates_generated_and_distributed",
                   network=network_name,
                   nodes=node_count)
    
    def _validate_certs_in_data_dirs(
        self, 
        node_count: int, 
        root_count: int, 
        network_name: str
    ) -> None:
        """
        Validate that required certificates exist in node data directories.
        
        Args:
            node_count: Total number of nodes
            root_count: Number of ROOT nodes
            network_name: Network name
            
        Raises:
            RuntimeError: If required certificates are missing
        """
        missing = []
        
        for node_id in range(1, node_count + 1):
            node_ca_dir = self.data_cache / f"node{node_id}" / "lib" / "ca"
            
            # Determine expected cert name based on role
            if node_id <= root_count:
                cert_idx = node_id - 1
                cert_name = f"{network_name}.root.pvt.{cert_idx}.dcert"
            else:
                cert_idx = node_id - root_count - 1
                cert_name = f"{network_name}.master.pvt.{cert_idx}.dcert"
            
            cert_path = node_ca_dir / cert_name
            if not cert_path.exists():
                missing.append(f"node{node_id}/lib/ca/{cert_name}")
        
        if missing:
            logger.error("certificates_missing_in_data_dirs",
                        missing=missing,
                        data_cache=str(self.data_cache))
            raise RuntimeError(
                f"Certificates missing in data directories: {missing[:5]}. "
                f"Check certificate generation and copy process."
            )
        
        logger.debug("certificates_validated_in_data_dirs", count=node_count)
    
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
                docker_client = docker.from_env(timeout=30)
                logger.debug("cleaning_data_cache_with_docker", path=str(self.data_cache))
                
                target_path = f"{CLEANUP_MOUNT_PATH}/data"
                cleanup_cmd = CLEANUP_CMD_TEMPLATE.format(target=target_path)
                
                docker_client.containers.run(
                    image=CLEANUP_IMAGE,
                    command=["sh", "-c", cleanup_cmd],
                    volumes={
                        str(self.cache_dir.absolute()): {
                            'bind': CLEANUP_MOUNT_PATH,
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

