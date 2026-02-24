"""
Genesis configuration management for Cellframe stagenet.

Handles updates to chain configuration files for genesis parameters.
"""

import re
from pathlib import Path
from typing import List, Optional

import docker
from jinja2 import Template

from .genesis_base import BaseGenesisManager
from .models import NodeConfig
from src.utils.logger import get_logger


logger = get_logger(__name__)


class GenesisConfigManager(BaseGenesisManager):
    """
    Manages genesis-related configuration updates.
    
    Responsibilities:
    - Retrieve genesis hashes from running nodes
    - Update static_genesis_* parameters in chain configs
    - Update fee_addr in mainchain config
    - Manage seed_mode configuration
    
    Inherits from BaseGenesisManager:
    - _exec_cli(): CLI command execution
    - _read_node_addr_from_cli(): Node address retrieval
    """
    
    async def get_genesis_event_hash(self, chain_name: str) -> Optional[str]:
        """
        Get genesis event hash from DAG chain.
        
        Args:
            chain_name: DAG chain name (e.g., "zerochain")
            
        Returns:
            Genesis event hash or None if not found
        """
        logger.info("getting_genesis_event", chain=chain_name)
        
        try:
            exit_code, stdout_str, _ = self._exec_cli(
                1,
                f"dag event list -net {self.network_name} -chain {chain_name} -from events -limit 1",
                check_output=False
            )
            
            if exit_code != 0:
                logger.warning("event_list_failed", chain=chain_name, exit_code=exit_code)
                return None
            
            # Parse event hash from output
            hash_match = re.search(r'event\s+hash:\s*(0x[A-Fa-f0-9]{64})', stdout_str, re.IGNORECASE)
            if hash_match:
                genesis_hash = hash_match.group(1)
                logger.info("genesis_event_found", chain=chain_name, hash=genesis_hash[:16])
                return genesis_hash
            
            # Try alternative format
            hash_match = re.search(r'(0x[A-Fa-f0-9]{64})', stdout_str)
            if hash_match:
                genesis_hash = hash_match.group(1)
                logger.info("genesis_event_found_alt_format", chain=chain_name, hash=genesis_hash[:16])
                return genesis_hash
            
            logger.warning("genesis_event_not_found", chain=chain_name, output=stdout_str[:200])
            return None
            
        except Exception as e:
            logger.error("genesis_event_retrieval_error", chain=chain_name, error=str(e))
            return None
    
    async def get_genesis_block_hash(self, chain_name: str) -> Optional[str]:
        """
        Get genesis block hash from blockchain chain.
        
        Args:
            chain_name: Blockchain chain name (e.g., "main")
            
        Returns:
            Genesis block hash or None if not found
        """
        logger.info("getting_genesis_block", chain=chain_name)
        
        try:
            exit_code, stdout_str, _ = self._exec_cli(
                1,
                f"block list -net {self.network_name} -chain {chain_name} -first 1",
                check_output=False
            )
            
            if exit_code != 0:
                logger.warning("block_list_failed", chain=chain_name, exit_code=exit_code)
                return None
            
            # Parse block hash from output
            hash_match = re.search(r'hash:\s*(0x[A-Fa-f0-9]{64})', stdout_str, re.IGNORECASE)
            if hash_match:
                genesis_hash = hash_match.group(1)
                logger.info("genesis_block_found", chain=chain_name, hash=genesis_hash[:16])
                return genesis_hash
            
            # Try alternative format
            hash_match = re.search(r'(0x[A-Fa-f0-9]{64})', stdout_str)
            if hash_match:
                genesis_hash = hash_match.group(1)
                logger.info("genesis_block_found_alt_format", chain=chain_name, hash=genesis_hash[:16])
                return genesis_hash
            
            logger.warning("genesis_block_not_found", chain=chain_name, output=stdout_str[:200])
            return None
            
        except Exception as e:
            logger.error("genesis_block_retrieval_error", chain=chain_name, error=str(e))
            return None
    
    async def update_fee_addr_in_config(self, fee_addr: str, node_configs: List[NodeConfig]) -> None:
        """
        Update fee_addr in main.cfg on ALL nodes (on HOST filesystem).
        
        Args:
            fee_addr: Fee collection wallet address
            node_configs: List of all node configurations
        """
        logger.info("updating_fee_addr_in_configs", 
                   fee_addr=fee_addr[:20] + "...",
                   nodes=len(node_configs))
        
        for node in node_configs:
            try:
                # Path: cache/configs/nodeN/network/NETWORK_NAME/main.cfg
                config_file = self.base_path / ".." / "testing" / "cache" / "configs" / f"node{node.node_id}" / "network" / self.network_name / "main.cfg"
                config_file = config_file.resolve()
                
                if not config_file.exists():
                    logger.warning("main_cfg_not_found",
                                  node=f"node{node.node_id}",
                                  path=str(config_file))
                    continue
                
                # Read, replace, write
                config_content = config_file.read_text()
                config_content = re.sub(
                    r"^fee_addr=.*",
                    f"fee_addr={fee_addr}",
                    config_content,
                    flags=re.MULTILINE
                )
                config_file.write_text(config_content)
                
                logger.debug("fee_addr_updated_on_host", node=f"node{node.node_id}")
                    
            except Exception as e:
                logger.error("update_fee_addr_error", node=f"node{node.node_id}", error=str(e))
        
        logger.info("fee_addr_updated_on_all_nodes")
    
    async def update_static_genesis_in_config(self, chain_name: str, genesis_hash: str, node_configs: List[NodeConfig]) -> None:
        """
        Update static_genesis parameters in chain config files on HOST filesystem.
        
        Auto-detects chain type:
        - DAG chains (zerochain): updates static_genesis_event + is_static_genesis_event
        - Blockchain chains (main): updates static_genesis_block + is_static_genesis_block
        
        Args:
            chain_name: Chain name (main or zerochain)
            genesis_hash: Genesis block/event hash (0x...)
            node_configs: List of all node configurations
        """
        # Detect chain type
        is_dag = chain_name.lower() in ["zerochain", "zero", "0"]
        # SDK reads: [dag] static_genesis_event (NOT static_genesis_event_hash!)
        # SDK reads: [blocks] static_genesis_block
        param_name = "static_genesis_event" if is_dag else "static_genesis_block"
        
        logger.info("updating_static_genesis_in_configs", 
                   chain=chain_name,
                   type="DAG_event" if is_dag else "blockchain_block",
                   parameter=param_name,
                   hash=genesis_hash[:16],
                   nodes=len(node_configs))
        
        for node in node_configs:
            try:
                # Update config on HOST filesystem (works for both running and stopped containers)
                # Configs are mounted from cache/configs/nodeN/network/NETWORK_NAME/ into containers
                # CRITICAL: Use cache_dir from config (same as ConfigGenerator)
                from ..config.manager import get_config_loader
                config_loader = get_config_loader()
                paths_config = config_loader.get_paths_config()
                if 'cache_dir' not in paths_config:
                    raise RuntimeError(
                        "CRITICAL: cache_dir not found in paths_config! "
                        "Cannot proceed without cache directory configuration."
                    )
                cache_dir_relative = paths_config['cache_dir']
                cache_dir = (self.base_path / cache_dir_relative).resolve()
                
                config_file = cache_dir / "configs" / f"node{node.node_id}" / "network" / self.network_name / f"{chain_name}.cfg"
                
                if not config_file.exists():
                    logger.warning("config_file_not_found", 
                                  node=f"node{node.node_id}",
                                  chain=chain_name,
                                  path=str(config_file))
                    continue
                
                # Read config
                config_content = config_file.read_text()
                
                # CRITICAL: Check if [dag] or [blocks] section exists
                section_name = "[dag]" if is_dag else "[blocks]"
                if section_name not in config_content:
                    # Add section if it doesn't exist
                    config_content += f"\n{section_name}\n"
                    logger.debug("added_missing_section_to_config",
                               node=f"node{node.node_id}",
                               section=section_name)
                
                # Update the genesis hash parameter (or add if missing)
                param_pattern = re.compile(f"^{re.escape(param_name)}=.*", re.MULTILINE)
                param_exists = param_pattern.search(config_content) is not None
                
                if param_exists:
                    # Parameter exists - update it
                    config_content = param_pattern.sub(
                        f"{param_name}={genesis_hash}",
                        config_content
                    )
                    logger.info("genesis_param_updated_in_config",
                               node=f"node{node.node_id}",
                               param=param_name,
                               hash=genesis_hash[:16],
                               note="Parameter existed - updated value")
                else:
                    # Parameter doesn't exist - add it to the section
                    # Find the section and add parameter after it
                    section_pattern = re.compile(f"^{re.escape(section_name)}\\s*$", re.MULTILINE)
                    match = section_pattern.search(config_content)
                    if match:
                        # Insert after section header
                        insert_pos = match.end()
                        config_content = config_content[:insert_pos] + f"\n{param_name}={genesis_hash}\n" + config_content[insert_pos:]
                        logger.info("genesis_param_added_to_section",
                                   node=f"node{node.node_id}",
                                   param=param_name,
                                   hash=genesis_hash[:16],
                                   note="Parameter added to existing section")
                    else:
                        # Section not found - append to end
                        config_content += f"\n{section_name}\n{param_name}={genesis_hash}\n"
                        logger.info("genesis_param_added_new_section",
                                   node=f"node{node.node_id}",
                                   param=param_name,
                                   hash=genesis_hash[:16],
                                   note="Parameter added to new section")
                
                # Also enable the is_static_genesis_* flag (or add if missing)
                flag_name = "is_static_genesis_event" if is_dag else "is_static_genesis_block"
                flag_pattern = re.compile(f"^{re.escape(flag_name)}=.*", re.MULTILINE)
                if flag_pattern.search(config_content):
                    # Flag exists - update it
                    config_content = flag_pattern.sub(
                        f"{flag_name}=true",
                        config_content
                    )
                else:
                    # Flag doesn't exist - add it to the section
                    section_pattern = re.compile(f"^{re.escape(section_name)}\\s*$", re.MULTILINE)
                    match = section_pattern.search(config_content)
                    if match:
                        insert_pos = match.end()
                        # Add flag after genesis hash parameter if it exists nearby, otherwise after section
                        param_line = config_content.find(f"{param_name}=")
                        if param_line != -1 and param_line > match.start():
                            # Insert after genesis hash parameter
                            line_end = config_content.find('\n', param_line)
                            if line_end != -1:
                                insert_pos = line_end + 1
                        config_content = config_content[:insert_pos] + f"{flag_name}=true\n" + config_content[insert_pos:]
                    else:
                        # Section not found - append to end
                        config_content += f"\n{flag_name}=true\n"
                
                # CRITICAL: Verify the parameter is actually in the content before writing
                if param_name not in config_content or genesis_hash not in config_content:
                    logger.error("genesis_hash_missing_in_content_before_write",
                               node=f"node{node.node_id}",
                               param=param_name,
                               hash=genesis_hash[:16],
                               param_in_content=param_name in config_content,
                               hash_in_content=genesis_hash in config_content,
                               note="CRITICAL: Parameter or hash not found in content before write!")
                
                # Write back
                config_file.write_text(config_content)
                
                # CRITICAL: Verify file was written correctly
                written_content = config_file.read_text()
                if genesis_hash not in written_content:
                    logger.error("genesis_hash_not_in_file_after_write",
                               node=f"node{node.node_id}",
                               hash=genesis_hash[:16],
                               file_path=str(config_file),
                               note="CRITICAL: Hash was not written to file!")
                else:
                    logger.info("genesis_hash_verified_in_file",
                               node=f"node{node.node_id}",
                               hash=genesis_hash[:16],
                               file_path=str(config_file),
                               note="Hash verified in file after write")
                
                logger.debug("genesis_hash_and_flag_updated_on_host", 
                            node=f"node{node.node_id}",
                            parameter=param_name,
                            flag=flag_name,
                            hash=genesis_hash[:16])
                    
            except Exception as e:
                logger.error("update_genesis_hash_error", node=f"node{node.node_id}", error=str(e))
        
        logger.info("genesis_hash_updated_on_all_nodes", chain=chain_name, parameter=param_name)
    
    def _regenerate_base_config(self, node_id: int, seed_mode: str) -> None:
        """
        Regenerate base config for a node using ConfigGenerator with updated context.
        
        This is the UNIFIED method for all config modifications - always regenerates
        from template with new context instead of manual string replacement.
        
        Args:
            node_id: Node ID to regenerate config for
            seed_mode: New seed_mode value ('true' or 'false')
        """
        from ..config.generator import ConfigGenerator
        
        # Get node IP from existing config
        node_config_file = self.base_path / ".." / "testing" / "cache" / "configs" / f"node{node_id}" / "cellframe-node.cfg"
        node_config_file = node_config_file.resolve()
        
        if not node_config_file.exists():
            logger.warning("config_not_found_for_regeneration", node_id=node_id)
            return
        
        # Extract node_ip from current config
        current_config = node_config_file.read_text()
        node_ip = None
        for line in current_config.split('\n'):
            if line.startswith('ext_address='):
                node_ip = line.split('=')[1].strip()
                break
        
        if not node_ip:
            logger.warning("node_ip_not_found_cannot_regenerate", node_id=node_id)
            return
        
        # Regenerate config from Jinja2 template with updated context
        from jinja2 import Template
        template_path = self.base_path / "config" / "templates" / "base" / "cellframe-node.cfg.j2"
        template_content = template_path.read_text()
        template = Template(template_content)
        
        # Render with updated context
        context = {
            'node_ip': node_ip,
            'seed_mode': seed_mode
        }
        new_config_content = template.render(**context)
        node_config_file.write_text(new_config_content)
        
        logger.debug("base_config_regenerated", node_id=node_id, seed_mode=seed_mode)
    
    def enable_seed_mode_in_configs(self, node_ids: List[int]) -> None:
        """
        Enable seed_mode by regenerating configs through unified generation system.
        
        Args:
            node_ids: List of node IDs to enable seed_mode for
        """
        logger.info("enabling_seed_mode_in_configs", node_ids=node_ids)
        
        for node_id in node_ids:
            try:
                self._regenerate_base_config(node_id, seed_mode='true')
            except Exception as e:
                logger.error("enable_seed_mode_error", node_id=node_id, error=str(e))
    
    def disable_seed_mode_in_configs_with_genesis_hash(
        self,
        node_ids: List[int],
        zerochain_genesis_hash: Optional[str] = None,
        mainchain_genesis_hash: Optional[str] = None,
        fee_addr: Optional[str] = None
    ) -> None:
        """
        Disable seed_mode by regenerating configs with EXPLICITLY PROVIDED genesis hashes.
        
        This prevents loss of static_genesis_event during regeneration by accepting
        genesis hashes as parameters instead of reading from potentially stale configs.
        
        Args:
            node_ids: List of node IDs to disable seed_mode for
            zerochain_genesis_hash: Zerochain genesis event hash (MUST be provided!)
            mainchain_genesis_hash: Mainchain genesis block hash (optional)
            fee_addr: Fee address (optional)
        """
        logger.info("disabling_seed_mode_in_configs_with_explicit_genesis_hash",
                   node_ids=node_ids,
                   zerochain_genesis_hash=zerochain_genesis_hash[:16] if zerochain_genesis_hash else None,
                   mainchain_genesis_hash=mainchain_genesis_hash[:16] if mainchain_genesis_hash else None,
                   fee_addr=fee_addr[:16] if fee_addr else None)
        
        # Regenerate base configs with seed_mode=false
        for node_id in node_ids:
            try:
                self._regenerate_base_config(node_id, seed_mode='false')
            except Exception as e:
                logger.error("disable_seed_mode_error", node_id=node_id, error=str(e))
        
        # Regenerate chain configs with PROVIDED genesis hashes
        self._regenerate_chain_configs_with_preserved_genesis(
            node_ids,
            zerochain_genesis_hash,
            mainchain_genesis_hash,
            fee_addr
        )
    
    def disable_seed_mode_in_configs(self, node_ids: List[int]) -> None:
        """
        Disable seed_mode by regenerating configs through unified generation system.
        
        CRITICAL: Also regenerates chain configs with preserved genesis event hashes
        to prevent loss of static_genesis_event during regeneration.
        
        Args:
            node_ids: List of node IDs to disable seed_mode for
        """
        logger.info("disabling_seed_mode_in_configs", node_ids=node_ids)
        
        # CRITICAL: Read genesis event hashes and fee_addr from existing configs BEFORE regeneration
        # This prevents loss of static_genesis_event and fee_addr during chain config regeneration
        zerochain_genesis_hash = None
        main_genesis_hash = None
        fee_addr = None
        
        if node_ids:
            # Read genesis hashes from first node's config (same for all nodes)
            first_node_id = node_ids[0]
            # CRITICAL: Use same cache_dir path as update_static_genesis_in_config
            # This ensures we read from the same location where genesis hash was written
            from ..config.manager import get_config_loader
            config_loader = get_config_loader()
            paths_config = config_loader.get_paths_config()
            if 'cache_dir' not in paths_config:
                raise RuntimeError(
                    "CRITICAL: cache_dir not found in paths_config! "
                    "Cannot proceed without cache directory configuration."
                )
            cache_dir_relative = paths_config['cache_dir']
            cache_dir = (self.base_path / cache_dir_relative).resolve()
            
            # Read zerochain genesis event hash using centralized config manager
            zerochain_config_path = cache_dir / "configs" / f"node{first_node_id}" / "network" / self.network_name / "zerochain.cfg"
            if zerochain_config_path.exists():
                from ..config.manager import get_config_loader
                config_loader = get_config_loader()
                config = config_loader.load_config_file(zerochain_config_path)
                if 'dag' not in config:
                    raise RuntimeError(
                        f"CRITICAL: [dag] section not found in zerochain.cfg at {zerochain_config_path}! "
                        f"Cannot preserve genesis hash without [dag] section."
                    )
                if 'static_genesis_event' not in config['dag']:
                    raise RuntimeError(
                        f"CRITICAL: static_genesis_event not found in [dag] section at {zerochain_config_path}! "
                        f"Cannot preserve genesis hash without static_genesis_event parameter."
                    )
                zerochain_genesis_hash = config['dag']['static_genesis_event'].strip()
                if not zerochain_genesis_hash:
                    raise RuntimeError(
                        f"CRITICAL: static_genesis_event is empty in config at {zerochain_config_path}! "
                        f"Cannot preserve empty genesis hash."
                    )
                logger.info("preserving_zerochain_genesis_hash_for_regeneration",
                          hash=zerochain_genesis_hash[:16])
            else:
                raise RuntimeError(
                    f"CRITICAL: zerochain.cfg not found at {zerochain_config_path}! "
                    f"Cannot preserve genesis hash without config file."
                )
            
            # Read main genesis block hash and fee_addr using centralized config manager
            main_config_path = cache_dir / "configs" / f"node{first_node_id}" / "network" / self.network_name / "main.cfg"
            if main_config_path.exists():
                from ..config.manager import get_config_loader
                config_loader = get_config_loader()
                config = config_loader.load_config_file(main_config_path)
                # Main genesis block hash is optional (only required for blockchain chains)
                if 'blocks' in config and 'static_genesis_block' in config['blocks']:
                    main_genesis_hash = config['blocks']['static_genesis_block'].strip()
                    if main_genesis_hash:
                        logger.info("preserving_main_genesis_hash_for_regeneration",
                                  hash=main_genesis_hash[:16])
                # Fee address must be present
                if 'esbocs' not in config:
                    raise RuntimeError(
                        f"CRITICAL: [esbocs] section not found in main.cfg at {main_config_path}! "
                        f"Cannot preserve fee_addr without [esbocs] section."
                    )
                if 'fee_addr' not in config['esbocs']:
                    raise RuntimeError(
                        f"CRITICAL: fee_addr not found in [esbocs] section at {main_config_path}! "
                        f"Cannot preserve fee_addr without fee_addr parameter."
                    )
                fee_addr = config['esbocs']['fee_addr'].strip()
                if not fee_addr:
                    raise RuntimeError(
                        f"CRITICAL: fee_addr is empty in config at {main_config_path}! "
                        f"Cannot preserve empty fee_addr."
                    )
                logger.info("preserving_fee_addr_for_regeneration",
                          fee_addr=fee_addr[:16])
        
        for node_id in node_ids:
            try:
                self._regenerate_base_config(node_id, seed_mode='false')
            except Exception as e:
                logger.error("disable_seed_mode_error", node_id=node_id, error=str(e))
        
        # CRITICAL: Regenerate chain configs with preserved genesis hashes and fee_addr
        if zerochain_genesis_hash or main_genesis_hash or fee_addr:
            logger.info("regenerating_chain_configs_with_preserved_genesis_hashes",
                       zerochain_genesis=zerochain_genesis_hash[:16] if zerochain_genesis_hash else None,
                       main_genesis=main_genesis_hash[:16] if main_genesis_hash else None,
                       fee_addr=fee_addr[:16] if fee_addr else None)
            self._regenerate_chain_configs_with_preserved_genesis(
                node_ids,
                zerochain_genesis_hash,
                main_genesis_hash,
                fee_addr
            )
    
    def _regenerate_chain_configs_with_preserved_genesis(
        self,
        node_ids: List[int],
        zerochain_genesis_hash: Optional[str],
        main_genesis_hash: Optional[str],
        fee_addr: Optional[str] = None
    ) -> None:
        """
        Regenerate chain configs for specified nodes, preserving static genesis hashes and fee_addr.
        
        This method is called after base configs are regenerated (e.g., to disable seed_mode)
        to ensure that chain-specific static genesis hashes and fee_addr are not lost.
        
        Args:
            node_ids: List of node IDs to regenerate chain configs for
            zerochain_genesis_hash: Preserved zerochain genesis event hash (or None)
            main_genesis_hash: Preserved main genesis block hash (or None)
            fee_addr: Preserved fee address (or None)
        """
        from ..config.generator import ConfigGenerator
        
        # Initialize ConfigGenerator to access templates and paths
        config_generator = ConfigGenerator(self.base_path, self.config_path)
        
        # CRITICAL: Read existing chain config parameters BEFORE regeneration
        # This ensures we preserve all parameters (auth_certs_number, root_nodes_addrs, etc.)
        # that are not part of genesis hashes
        existing_zerochain_params = {}
        existing_main_params = {}
        
        if node_ids:
            # Read from first node's config (same for all nodes)
            first_node_id = node_ids[0]
            zerochain_config_path = config_generator.configs_cache / f"node{first_node_id}" / "network" / self.network_name / "zerochain.cfg"
            
            if zerochain_config_path.exists():
                # Use centralized config manager
                from ..config.manager import get_config_loader
                config_loader = get_config_loader()
                existing_config = config_loader.load_config_file(zerochain_config_path)
                
                # Read zerochain parameters
                if 'dag-poa' in existing_config:
                    if 'auth_certs_number' not in existing_config['dag-poa']:
                        raise RuntimeError(
                            f"CRITICAL: auth_certs_number not found in [dag-poa] section! "
                            f"Cannot regenerate config without auth_certs_number parameter."
                        )
                    if 'auth_certs_number_verify' not in existing_config['dag-poa']:
                        raise RuntimeError(
                            f"CRITICAL: auth_certs_number_verify not found in [dag-poa] section! "
                            f"Cannot regenerate config without auth_certs_number_verify parameter."
                        )
                    existing_zerochain_params['auth_certs_number'] = existing_config['dag-poa']['auth_certs_number'].strip()
                    existing_zerochain_params['auth_certs_number_verify'] = existing_config['dag-poa']['auth_certs_number_verify'].strip()
                else:
                    raise RuntimeError(
                        f"CRITICAL: [dag-poa] section not found in zerochain config! "
                        f"Cannot regenerate config without dag-poa parameters."
                    )
                
                if 'chain' in existing_config:
                    if 'authorized_nodes_addrs' not in existing_config['chain']:
                        raise RuntimeError(
                            f"CRITICAL: authorized_nodes_addrs not found in [chain] section! "
                            f"Cannot regenerate config without authorized_nodes_addrs parameter."
                        )
                    existing_zerochain_params['authorized_nodes_addrs'] = existing_config['chain']['authorized_nodes_addrs'].strip()
                else:
                    raise RuntimeError(
                        f"CRITICAL: [chain] section not found in zerochain config! "
                        f"Cannot regenerate config without chain parameters."
                    )
            
            # Read main chain parameters
            main_config_path = config_generator.configs_cache / f"node{first_node_id}" / "network" / self.network_name / "main.cfg"
            if main_config_path.exists():
                # Use centralized config manager
                from ..config.manager import get_config_loader
                config_loader = get_config_loader()
                existing_config = config_loader.load_config_file(main_config_path)
                
                # Read main chain parameters
                if 'esbocs' not in existing_config:
                    raise RuntimeError(
                        f"CRITICAL: [esbocs] section not found in main config! "
                        f"Cannot regenerate config without esbocs parameters."
                    )
                
                if 'validators_addrs' not in existing_config['esbocs']:
                    raise RuntimeError(
                        f"CRITICAL: validators_addrs not found in [esbocs] section! "
                        f"Cannot regenerate config without validators_addrs parameter."
                    )
                if 'auth_certs_prefix' not in existing_config['esbocs']:
                    raise RuntimeError(
                        f"CRITICAL: auth_certs_prefix not found in [esbocs] section! "
                        f"Cannot regenerate config without auth_certs_prefix parameter."
                    )
                
                validators_addrs_from_config = existing_config['esbocs']['validators_addrs'].strip()
                existing_main_params['validators_addrs'] = validators_addrs_from_config
                existing_main_params['auth_certs_prefix'] = existing_config['esbocs']['auth_certs_prefix'].strip()
                
                # CRITICAL: If validators_addrs is empty in config, re-collect from certificates
                # This handles the case where config was generated before certificates were ready
                if validators_addrs_from_config == '[]' or not validators_addrs_from_config.strip():
                    logger.warning("validators_addrs_empty_in_config_recollecting",
                                 note="validators_addrs is empty in config - recollecting from certificates")
                    # Re-collect master validator addresses from certificates
                    # NodeConfig is already imported at module level
                    all_nodes = config_generator.topology_loader.load_topology()
                    master_nodes = [n for n in all_nodes if n.consensus_participation and not n.is_seed_node]
                    recollected_addrs = config_generator._collect_validator_addresses(master_nodes, self.network_name)
                    if recollected_addrs and recollected_addrs != '[]':
                        existing_main_params['validators_addrs'] = recollected_addrs
                        logger.info("validators_addrs_recollected_from_certificates",
                                  validators=recollected_addrs[:50],
                                  count=len(master_nodes),
                                  note="Re-collected master validator addresses from certificates")
                    else:
                        raise RuntimeError(
                            f"CRITICAL: Failed to re-collect validators_addrs from certificates! "
                            f"validators_addrs is empty in config and cannot be recollected."
                        )
                
                # CRITICAL: Preserve fee_addr from existing config if not provided
                if not fee_addr:
                    if 'fee_addr' not in existing_config['esbocs']:
                        raise RuntimeError(
                            f"CRITICAL: fee_addr not found in [esbocs] section and not provided as parameter! "
                            f"Cannot regenerate config without fee_addr."
                        )
                    existing_fee_addr = existing_config['esbocs']['fee_addr'].strip()
                    if not existing_fee_addr:
                        raise RuntimeError(
                            f"CRITICAL: fee_addr is empty in existing config and not provided as parameter! "
                            f"Cannot regenerate config without fee_addr."
                        )
                    fee_addr = existing_fee_addr
                    logger.info("preserving_fee_addr_from_existing_config",
                              fee_addr=fee_addr[:16],
                              note="fee_addr not provided, reading from existing config")
        
        # CRITICAL: Keep existing validators_addrs and determine min_validators_count
        # IMPORTANT: SDK check in dap_chain_cs_esbocs.c line 298:
        #   if (!l_validators_count || l_node_addrs_count < l_validators_count) return -2;
        # SDK REQUIRES: validators_addrs must contain AT LEAST min_validators_count addresses
        # 
        # PoA mode is implicit when validators_addrs is specified in config
        # validators_addrs already contains master node addresses (set during initial config generation)
        if 'validators_addrs' not in existing_main_params:
            raise RuntimeError(
                f"CRITICAL: validators_addrs not found in existing_main_params! "
                f"Cannot regenerate config without validators_addrs."
            )
        validators_addrs_value = existing_main_params['validators_addrs']
        
        # Extract validator count from validators_addrs to calculate min_validators_count
        import re
        if validators_addrs_value and validators_addrs_value != '[]':
            validators_list = re.findall(r'[A-Fa-f0-9:]+', validators_addrs_value)
            validator_count = len(validators_list)
            min_validators_count = max(1, validator_count // 2 + 1)  # 2/3 consensus
            logger.info("min_validators_count_calculated_from_existing_validators",
                       validator_count=validator_count,
                       min_validators_count=min_validators_count,
                       note="Using existing validators_addrs from config")
        else:
            # No validators in config - should not happen after initial generation
            min_validators_count = 1  # Default
            logger.warning("no_validators_addrs_in_existing_config",
                         note="validators_addrs is empty - using default min_validators_count=1")
        
        # Prepare Jinja2 context with preserved genesis hashes, fee_addr AND existing parameters
        chain_context = {
            'static_genesis_event': zerochain_genesis_hash if zerochain_genesis_hash else '',
            'is_static_genesis_event': 'true' if zerochain_genesis_hash else 'false',
            'static_genesis_block': main_genesis_hash if main_genesis_hash else '',
            'is_static_genesis_block': 'true' if main_genesis_hash else 'false',
            # Preserve existing parameters from config files
            'auth_certs_number': existing_zerochain_params['auth_certs_number'],
            'auth_certs_number_verify': existing_zerochain_params['auth_certs_number_verify'],
            'root_nodes_addrs': existing_zerochain_params['authorized_nodes_addrs'],
            'validators_addrs': validators_addrs_value,  # Keep for zerochain compatibility
            'mainchain_validators_addrs': validators_addrs_value,  # CRITICAL: Master validators for mainchain
            'min_validators_count': min_validators_count,  # CRITICAL: Set based on validators_addrs
            'poa_mode': 'true',  # CRITICAL: Always use PoA mode (validators specified in config)
            'fee_addr': fee_addr if fee_addr else '',  # Use preserved fee_addr or empty string
            'genesis_mode': 'false',  # Disable genesis mode after genesis
        }
        
        # Log fee_addr preservation
        if fee_addr:
            logger.info("fee_addr_preserved_in_chain_context",
                       fee_addr=fee_addr[:16],
                       note="fee_addr will be preserved in regenerated configs")
        else:
            logger.warning("fee_addr_not_preserved_in_chain_context",
                         note="fee_addr is empty - regenerated configs will have empty fee_addr")
        
        logger.info("chain_context_prepared_for_regeneration",
                   zerochain_genesis=zerochain_genesis_hash[:16] if zerochain_genesis_hash else None,
                   main_genesis=main_genesis_hash[:16] if main_genesis_hash else None,
                   fee_addr=chain_context['fee_addr'][:16] if chain_context['fee_addr'] else 'empty',
                   auth_certs_number=chain_context['auth_certs_number'],
                   root_nodes_addrs_preview=chain_context['root_nodes_addrs'][:50] if chain_context['root_nodes_addrs'] else 'empty')
        
        # Render all chain templates ONCE with the preserved genesis hashes
        rendered_chain_configs = {}
        chains_template_dir = config_generator.templates_dir / "chains"
        if not chains_template_dir.exists():
            logger.error("chain_templates_directory_missing", path=str(chains_template_dir))
            return
        
        for chain_template in chains_template_dir.glob("*.cfg.j2"):
            chain_template_content = chain_template.read_text()
            template = Template(chain_template_content)
            chain_content = template.render(**chain_context)
            output_name = chain_template.stem
            rendered_chain_configs[output_name] = chain_content
            logger.debug("chain_config_re_rendered_with_genesis",
                       chain=output_name,
                       zerochain_genesis=zerochain_genesis_hash[:16] if zerochain_genesis_hash else None,
                       main_genesis=main_genesis_hash[:16] if main_genesis_hash else None)
        
        # CRITICAL: Fail-fast if critical parameters are missing
        if "zerochain.cfg" in rendered_chain_configs:
            if not zerochain_genesis_hash:
                logger.error("critical_zerochain_genesis_hash_missing_during_regeneration",
                           zerochain_genesis_hash=zerochain_genesis_hash,
                           note="CRITICAL: zerochain_genesis_hash is None - cannot regenerate zerochain.cfg without it!")
                raise RuntimeError(
                    f"CRITICAL: zerochain_genesis_hash is None when trying to regenerate zerochain.cfg! "
                    f"This means static_genesis_event was not read from config before regeneration. "
                    f"Cannot proceed - this would overwrite config with empty static_genesis_event."
                )
            
            if not chain_context['auth_certs_number'] or not chain_context['root_nodes_addrs']:
                raise RuntimeError(
                    f"CRITICAL: auth_certs_number or root_nodes_addrs is empty when trying to regenerate zerochain.cfg! "
                    f"auth_certs_number={chain_context['auth_certs_number']}, "
                    f"root_nodes_addrs={chain_context['root_nodes_addrs'][:50]}. "
                    f"Cannot proceed - this would overwrite config with empty parameters."
                )
        
        # Write regenerated chain configs for specified nodes
        for node_id in node_ids:
            node_network_base = config_generator.configs_cache / f"node{node_id}" / "network"
            node_chains_dir = node_network_base / self.network_name
            node_chains_dir.mkdir(parents=True, exist_ok=True) # Ensure directory exists
            
            for chain_name, chain_content in rendered_chain_configs.items():
                dst_chain_cfg = node_chains_dir / chain_name
                dst_chain_cfg.write_text(chain_content)
                logger.debug("chain_config_re_written_with_genesis",
                           node_id=node_id,
                           chain=chain_name,
                           path=str(dst_chain_cfg))
        
        logger.info("chain_configs_regenerated_with_preserved_genesis_hashes_complete",
                   nodes=len(node_ids),
                   chains=len(rendered_chain_configs))
    
    def read_static_genesis_event_from_config(self, chain_name: str, node_id: int) -> Optional[str]:
        """
        Read static_genesis_event from chain config file on HOST filesystem.
        
        Args:
            chain_name: Chain name (e.g., "zerochain")
            node_id: Node ID
            
        Returns:
            Genesis event hash or None if not found
        """
        try:
            from ..config.manager import get_config_loader
            config_loader = get_config_loader()
            paths_config = config_loader.get_paths_config()
            if 'cache_dir' not in paths_config:
                raise RuntimeError(
                    "CRITICAL: cache_dir not found in paths_config! "
                    "Cannot proceed without cache directory configuration."
                )
            cache_dir_relative = paths_config['cache_dir']
            cache_dir = (self.base_path / cache_dir_relative).resolve()
            
            config_file = cache_dir / "configs" / f"node{node_id}" / "network" / self.network_name / f"{chain_name}.cfg"
            
            if not config_file.exists():
                logger.warning("config_file_not_found_for_reading_genesis",
                             node_id=node_id,
                             chain=chain_name,
                             path=str(config_file))
                return None
            
            # Use centralized config manager
            config_loader = get_config_loader()
            config = config_loader.load_config_file(config_file)
            
            if 'dag' not in config:
                raise RuntimeError(
                    f"CRITICAL: [dag] section not found in config at {config_file}! "
                    f"Cannot read static_genesis_event without [dag] section."
                )
            
            if 'static_genesis_event' not in config['dag']:
                raise RuntimeError(
                    f"CRITICAL: static_genesis_event not found in [dag] section at {config_file}! "
                    f"Cannot read genesis event hash without static_genesis_event parameter."
                )
            
            static_genesis_event = config['dag']['static_genesis_event'].strip()
            if not static_genesis_event:
                raise RuntimeError(
                    f"CRITICAL: static_genesis_event is empty in config at {config_file}! "
                    f"Cannot use empty genesis event hash."
                )
            
            logger.info("static_genesis_event_read_from_config",
                      node_id=node_id,
                      chain=chain_name,
                      hash=static_genesis_event[:16],
                      path=str(config_file))
            return static_genesis_event
            
        except Exception as e:
            logger.error("failed_to_read_static_genesis_event_from_config",
                        node_id=node_id,
                        chain=chain_name,
                        error=str(e))
            return None
    
    def read_fee_addr_from_config(self, node_id: int) -> str:
        """
        Read fee_addr from mainchain config file.
        
        Args:
            node_id: Node ID
            
        Returns:
            Fee address string
            
        Raises:
            RuntimeError: If fee_addr not found (FAIL-FAST)
        """
        from ..config.manager import get_config_loader
        config_loader = get_config_loader()
        paths_config = config_loader.get_paths_config()
        
        if 'cache_dir' not in paths_config:
            raise RuntimeError("cache_dir not found in paths_config")
        
        cache_dir_relative = paths_config['cache_dir']
        cache_dir = (self.base_path / cache_dir_relative).resolve()
        
        config_file = cache_dir / "configs" / f"node{node_id}" / "network" / self.network_name / "main.cfg"
        
        if not config_file.exists():
            raise RuntimeError(f"Config file not found: {config_file}")
        
        config = config_loader.load_config_file(config_file)
        
        if 'esbocs' not in config:
            raise RuntimeError(f"[esbocs] section not found in {config_file}")
        
        if 'fee_addr' not in config['esbocs']:
            raise RuntimeError(f"fee_addr not found in [esbocs] section at {config_file}")
        
        fee_addr = config['esbocs'].get('fee_addr', '').strip()
        if not fee_addr:
            raise RuntimeError(f"fee_addr is empty in {config_file}")
        
        return fee_addr
    
    def disable_genesis_mode_in_chain_configs(self, chain_name: str, node_ids: List[int]) -> None:
        """
        Disable genesis_mode in chain config files after genesis block is created.
        
        Args:
            chain_name: Chain name (main or zerochain)
            node_ids: List of node IDs to disable genesis_mode for
        """
        logger.info("disabling_genesis_mode_in_chain_configs", chain=chain_name, node_ids=node_ids)
        
        for node_id in node_ids:
            try:
                # Find chain config file (same path as update_static_genesis_in_config)
                config_file = self.base_path / ".." / "testing" / "cache" / "configs" / f"node{node_id}" / "network" / self.network_name / f"{chain_name}.cfg"
                config_file = config_file.resolve()
                
                if not config_file.exists():
                    logger.warning("chain_config_not_found", node_id=node_id, chain=chain_name, path=str(config_file))
                    continue
                
                # Read config file
                config_content = config_file.read_text()
                
                # Replace genesis_mode=true with genesis_mode=false
                # Match both genesis_mode=true and genesis_mode = true (with spaces)
                pattern = r'genesis_mode\s*=\s*true'
                if re.search(pattern, config_content, re.IGNORECASE):
                    config_content = re.sub(pattern, 'genesis_mode=false', config_content, flags=re.IGNORECASE)
                    config_file.write_text(config_content)
                    logger.debug("genesis_mode_disabled", node_id=node_id, chain=chain_name)
                else:
                    logger.debug("genesis_mode_not_found_in_config", node_id=node_id, chain=chain_name)
                    
            except Exception as e:
                logger.error("disable_genesis_mode_error", node_id=node_id, chain=chain_name, error=str(e))

