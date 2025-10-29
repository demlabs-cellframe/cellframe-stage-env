"""
Genesis configuration management for Cellframe stagenet.

Handles updates to chain configuration files for genesis parameters.
"""

import re
from pathlib import Path
from typing import List, Optional

import docker

from .genesis_base import BaseGenesisManager
from .models import NodeConfig
from ..utils.logger import get_logger


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
                config_file = self.base_path / ".." / "testing" / "cache" / "configs" / f"node{node.node_id}" / "network" / self.network_name / f"{chain_name}.cfg"
                config_file = config_file.resolve()
                
                if not config_file.exists():
                    logger.warning("config_file_not_found", 
                                  node=f"node{node.node_id}",
                                  chain=chain_name,
                                  path=str(config_file))
                    continue
                
                # Read config
                config_content = config_file.read_text()
                
                # Update the genesis hash parameter
                config_content = re.sub(
                    f"^{param_name}=.*",
                    f"{param_name}={genesis_hash}",
                    config_content,
                    flags=re.MULTILINE
                )
                
                # Also enable the is_static_genesis_* flag
                flag_name = "is_static_genesis_event" if is_dag else "is_static_genesis_block"
                config_content = re.sub(
                    f"^{flag_name}=.*",
                    f"{flag_name}=true",
                    config_content,
                    flags=re.MULTILINE
                )
                
                # Write back
                config_file.write_text(config_content)
                
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
    
    def disable_seed_mode_in_configs(self, node_ids: List[int]) -> None:
        """
        Disable seed_mode by regenerating configs through unified generation system.
        
        Args:
            node_ids: List of node IDs to disable seed_mode for
        """
        logger.info("disabling_seed_mode_in_configs", node_ids=node_ids)
        
        for node_id in node_ids:
            try:
                self._regenerate_base_config(node_id, seed_mode='false')
            except Exception as e:
                logger.error("disable_seed_mode_error", node_id=node_id, error=str(e))

