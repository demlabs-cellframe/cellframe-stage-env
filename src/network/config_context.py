"""
Configuration Context Management for Cellframe Node Genesis.

Provides a unified system for managing Jinja2 template variables and generating configs.
Replaces manual file editing with template-based regeneration from a single source of truth.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import structlog

from .models import NodeConfig

logger = structlog.get_logger(__name__)


@dataclass
class ConfigContext:
    """
    Unified context for configuration generation.
    
    Single source of truth for all Jinja2 template variables.
    Replaces manual file editing with template-based regeneration.
    """
    
    # Network-wide parameters
    network_name: str
    base_path: Path
    config_path: Optional[Path] = None
    
    # Chain genesis hashes
    zerochain_genesis_hash: Optional[str] = None
    mainchain_genesis_hash: Optional[str] = None
    
    # Fee and validator addresses
    fee_addr: Optional[str] = None
    validators_addrs: str = "[]"
    mainchain_validators_addrs: str = "[]"
    root_nodes_addrs: str = "[]"
    
    # Consensus parameters
    min_validators_count: int = 2
    poa_mode: str = "true"
    auth_certs_number: int = 3
    auth_certs_number_verify: int = 2
    
    # Mode flags (per-node overrides stored separately)
    default_seed_mode: str = "false"
    default_genesis_mode: str = "false"
    
    # Per-node overrides
    node_overrides: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    
    def set_variable(self, key: str, value: Any, node_id: Optional[int] = None) -> None:
        """
        Set a single context variable.
        
        Args:
            key: Variable name
            value: Variable value
            node_id: Optional node ID for per-node override
        """
        if node_id is not None:
            # Per-node override
            if node_id not in self.node_overrides:
                self.node_overrides[node_id] = {}
            self.node_overrides[node_id][key] = value
            logger.debug("context_variable_set_for_node",
                       key=key,
                       value=str(value)[:50] if isinstance(value, str) else value,
                       node_id=node_id)
        else:
            # Global variable
            if hasattr(self, key):
                setattr(self, key, value)
                logger.debug("context_variable_set_global",
                           key=key,
                           value=str(value)[:50] if isinstance(value, str) else value)
            else:
                logger.warning("unknown_context_variable",
                             key=key,
                             note=f"Variable '{key}' not defined in ConfigContext")
    
    def update_variables(self, variables: Dict[str, Any], node_id: Optional[int] = None) -> None:
        """
        Update multiple context variables at once.
        
        Args:
            variables: Dictionary of variable names and values
            node_id: Optional node ID for per-node overrides
        """
        for key, value in variables.items():
            self.set_variable(key, value, node_id=node_id)
        
        logger.info("context_variables_updated",
                   count=len(variables),
                   keys=list(variables.keys()),
                   node_id=node_id if node_id else "global")
    
    def get_context_for_node(self, node_id: int, node_config: NodeConfig) -> Dict[str, Any]:
        """
        Get full Jinja2 context for a specific node.
        
        Merges global context with node-specific overrides.
        
        Args:
            node_id: Node ID
            node_config: Node configuration
            
        Returns:
            Complete Jinja2 context dictionary for this node
        """
        # Start with global context
        context = {
            'static_genesis_event': self.zerochain_genesis_hash if self.zerochain_genesis_hash else '',
            'is_static_genesis_event': 'true' if self.zerochain_genesis_hash else 'false',
            'static_genesis_block': self.mainchain_genesis_hash if self.mainchain_genesis_hash else '',
            'is_static_genesis_block': 'true' if self.mainchain_genesis_hash else 'false',
            'fee_addr': self.fee_addr if self.fee_addr else '',
            'validators_addrs': self.validators_addrs,
            'mainchain_validators_addrs': self.mainchain_validators_addrs,
            'root_nodes_addrs': self.root_nodes_addrs,
            'min_validators_count': self.min_validators_count,
            'poa_mode': self.poa_mode,
            'auth_certs_number': self.auth_certs_number,
            'auth_certs_number_verify': self.auth_certs_number_verify,
            'seed_mode': self.default_seed_mode,
            'genesis_mode': self.default_genesis_mode,
        }
        
        # Apply node-specific overrides
        if node_id in self.node_overrides:
            context.update(self.node_overrides[node_id])
        
        return context
    
    def regenerate_config(
        self,
        config_type: str,  # 'base', 'network', or 'chain'
        template_path: Path,
        output_path: Path,
        node_id: int,
        node_config: NodeConfig,
        extra_context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Regenerate a single config file from template using current context.
        
        Args:
            config_type: Type of config ('base', 'network', 'chain')
            template_path: Path to Jinja2 template file
            output_path: Path to write generated config
            node_id: Node ID
            node_config: Node configuration
            extra_context: Optional additional context variables
        """
        from jinja2 import Template
        
        # Get full context for this node
        context = self.get_context_for_node(node_id, node_config)
        
        # Add extra context if provided
        if extra_context:
            context.update(extra_context)
        
        # Read template
        template_content = template_path.read_text()
        template = Template(template_content)
        
        # Render config
        config_content = template.render(**context)
        
        # Write to output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(config_content)
        
        logger.debug("config_regenerated_from_context",
                   config_type=config_type,
                   node_id=node_id,
                   output_path=str(output_path),
                   template=template_path.name)
    
    def regenerate_all_configs_for_nodes(
        self,
        node_ids: List[int],
        nodes: List[NodeConfig],
        templates_dir: Path,
        output_base: Path
    ) -> None:
        """
        Regenerate ALL configs (base + network + chains) for specified nodes.
        
        Uses current context state - all variables must be set before calling this.
        
        Args:
            node_ids: List of node IDs to regenerate configs for
            nodes: List of all node configurations
            templates_dir: Directory containing Jinja2 templates
            output_base: Base output directory (cache/configs/)
        """
        from jinja2 import Template
        
        logger.info("regenerating_all_configs_from_context",
                   node_ids=node_ids,
                   variables={
                       'zerochain_genesis_hash': self.zerochain_genesis_hash[:16] if self.zerochain_genesis_hash else None,
                       'mainchain_genesis_hash': self.mainchain_genesis_hash[:16] if self.mainchain_genesis_hash else None,
                       'fee_addr': self.fee_addr[:16] if self.fee_addr else None,
                       'validators_addrs': self.validators_addrs[:50],
                       'mainchain_validators_addrs': self.mainchain_validators_addrs[:50],
                       'min_validators_count': self.min_validators_count,
                       'poa_mode': self.poa_mode,
                   })
        
        # Load chain templates
        chains_template_dir = templates_dir / "chains"
        chain_templates = {}
        for chain_template_file in chains_template_dir.glob("*.cfg.j2"):
            chain_templates[chain_template_file.stem] = Template(chain_template_file.read_text())
        
        # Regenerate for each node
        for node_id in node_ids:
            # Find node config
            node_config = next((n for n in nodes if n.node_id == node_id), None)
            if not node_config:
                logger.warning("node_config_not_found_skipping_regeneration",
                             node_id=node_id)
                continue
            
            # Get context for this node
            context = self.get_context_for_node(node_id, node_config)
            
            # Regenerate chain configs
            node_chains_dir = output_base / f"node{node_id}" / "network" / self.network_name
            node_chains_dir.mkdir(parents=True, exist_ok=True)
            
            for chain_name, chain_template in chain_templates.items():
                chain_content = chain_template.render(**context)
                output_file = node_chains_dir / f"{chain_name}.cfg"
                output_file.write_text(chain_content)
                
                logger.debug("chain_config_regenerated_from_context",
                           node_id=node_id,
                           chain=chain_name,
                           output=str(output_file))
        
        logger.info("all_configs_regenerated_from_context",
                   nodes=len(node_ids),
                   chains=len(chain_templates))

