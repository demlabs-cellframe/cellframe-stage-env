"""
Configuration loader for stage environment.

Handles loading and validation of:
- Stage environment config (stage-env.cfg)
- Network topologies (JSON templates)
- Template configurations (Jinja2)
"""

import json
import configparser
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from jinja2 import Environment, FileSystemLoader, Template
from pydantic import BaseModel, Field, field_validator

from ..utils.logger import get_logger

logger = get_logger(__name__)


class NetworkTopology(BaseModel):
    """Network topology configuration."""
    
    class Network(BaseModel):
        name: str
        network_id: str
        consensus: str
    
    class TopologyNode(BaseModel):
        count: int = Field(ge=0)
        role: str
        consensus_participation: bool = False
        is_seed_node: bool = False
        balancer_enabled: bool = False
        description: str = ""
    
    class Consensus(BaseModel):
        type: str
        min_validators: int = Field(ge=1)
        new_round_delay: int = Field(ge=1)
        collecting_level: float = Field(ge=0.0, le=100.0)
        auth_certs_prefix: str
    
    class Balancer(BaseModel):
        enabled: bool = False
        type: str = "http"  # http or dns
        uri: str = "f0intlt4eyl03htogu"
        max_links_response: int = 10
        request_delay: int = 20
    
    class NetworkSettings(BaseModel):
        base_rpc_port: int = Field(ge=1024, le=65535)
        base_p2p_port: int = Field(ge=1024, le=65535)
        base_cf_port: int = Field(ge=1024, le=65535)
        base_http_port: int = Field(ge=1024, le=65535)
        node_port: int = Field(8079, ge=1024, le=65535, description="Standard Cellframe node port for P2P/HTTP")
        base_ip: str
        subnet: str
    
    class Build(BaseModel):
        type: str = "debug"
        cellframe_version: str = "latest"
    
    network: Network
    topology: Dict[str, TopologyNode]
    consensus: Consensus
    balancer: Balancer = Balancer()
    network_settings: NetworkSettings
    build: Build
    features: Dict[str, bool] = {}
    
    @field_validator("topology")
    @classmethod
    def validate_topology(cls, v):
        """Ensure at least one node type is defined."""
        if not v:
            raise ValueError("Topology must define at least one node type")
        return v


class ConfigLoader:
    """Load and manage stage environment configurations."""
    
    def __init__(self, base_path: Path):
        """
        Initialize configuration loader.
        
        Args:
            base_path: Base path to stage-env directory
        """
        self.base_path = base_path
        self.config_dir = base_path / "config"
        self.topologies_dir = self.config_dir / "topologies"
        self.templates_dir = self.config_dir / "templates"
        
        # Setup Jinja2 environment
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=False,
        )
        
        logger.debug("config_loader_initialized", base_path=str(base_path))
    
    def load_stage_config(self) -> Dict[str, Any]:
        """
        Load stage-env configuration file.
        Creates from .default if not exists.
        
        Returns:
            Configuration dictionary with all default values
        """
        config_file = self.config_dir / "stage-env.cfg"
        default_file = self.config_dir / "stage-env.cfg.default"
        
        # Create from default if doesn't exist
        if not config_file.exists() and default_file.exists():
            logger.info("creating_config_from_default")
            import shutil
            shutil.copy2(default_file, config_file)
        
        # Load config
        if not config_file.exists():
            logger.error("config_not_found", path=str(config_file))
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        
        config = configparser.ConfigParser()
        config.read(config_file)
        
        # Convert to flat dictionary for Jinja2
        result = {}
        for section in config.sections():
            for key, value in config.items(section):
                # Try to parse as int/float/bool
                if value.lower() in ('true', 'false'):
                    result[key] = value.lower() == 'true'
                elif value.replace('.', '', 1).isdigit():
                    result[key] = float(value) if '.' in value else int(value)
                else:
                    result[key] = value
        
        logger.debug("config_loaded", keys=len(result))
        return result
    
    def load_topology(self, name: str = "default", context: Dict[str, Any] = None) -> NetworkTopology:
        """
        Load network topology configuration from Jinja2 template.
        
        Args:
            name: Topology name (without extension)
            context: Template context variables (merged with stage-env.cfg)
            
        Returns:
            Validated NetworkTopology object
            
        Raises:
            FileNotFoundError: If topology template doesn't exist
            ValueError: If topology is invalid
        """
        template_file = self.topologies_dir / f"{name}.json.tpl"
        
        if not template_file.exists():
            logger.error("topology_template_not_found", topology=name, 
                        path=str(template_file))
            raise FileNotFoundError(
                f"Topology template '{name}.json.tpl' not found at {template_file}"
            )
        
        logger.info("loading_topology_from_template", topology=name)
        
        # Load stage-env.cfg defaults
        config_context = self.load_stage_config()
        
        # Merge with provided context (provided context takes precedence)
        if context:
            config_context.update(context)
        
        # Render template
        with open(template_file) as f:
            template_content = f.read()
        
        from jinja2 import Template
        template = Template(template_content)
        rendered = template.render(**config_context)
        data = json.loads(rendered)
        
        topology = NetworkTopology(**data)
        logger.debug("topology_loaded", 
                    network=topology.network.name,
                    node_types=len(topology.topology))
        
        return topology
    
    def render_template(
        self,
        template_name: str,
        context: Dict[str, Any],
    ) -> str:
        """
        Render Jinja2 template with context.
        
        Args:
            template_name: Template filename (relative to templates/)
            context: Template context variables
            
        Returns:
            Rendered template string
        """
        logger.debug("rendering_template", template=template_name)
        
        template = self.jinja_env.get_template(template_name)
        return template.render(**context)
    
    def load_yaml(self, file_path: Path) -> Dict[str, Any]:
        """
        Load YAML configuration file.
        
        Args:
            file_path: Path to YAML file
            
        Returns:
            Parsed YAML data
        """
        logger.debug("loading_yaml", path=str(file_path))
        
        with open(file_path) as f:
            return yaml.safe_load(f)
    
    def save_yaml(self, data: Dict[str, Any], file_path: Path) -> None:
        """
        Save data to YAML file.
        
        Args:
            data: Data to save
            file_path: Output file path
        """
        logger.debug("saving_yaml", path=str(file_path))
        
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(file_path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
    
    def get_node_count(self, topology: NetworkTopology) -> int:
        """
        Calculate total number of nodes in topology.
        
        Args:
            topology: Network topology
            
        Returns:
            Total node count
        """
        return sum(node.count for node in topology.topology.values())
    
    def list_topologies(self) -> list[str]:
        """
        List available topology names.
        
        Returns:
            List of topology names (without .json extension)
        """
        if not self.topologies_dir.exists():
            return []
        
        return [
            f.stem for f in self.topologies_dir.glob("*.json")
        ]

