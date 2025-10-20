"""
Configuration loader for stage environment.

Handles loading and validation of:
- Network topologies (JSON)
- Template configurations (Jinja2)
- Environment settings (YAML)
"""

import json
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
        consensus_participation: bool
        description: str
    
    class Consensus(BaseModel):
        type: str
        min_validators: int = Field(ge=1)
        new_round_delay: int = Field(ge=1)
        collecting_level: float = Field(ge=0.0, le=100.0)
        auth_certs_prefix: str
    
    class NetworkSettings(BaseModel):
        base_rpc_port: int = Field(ge=1024, le=65535)
        base_p2p_port: int = Field(ge=1024, le=65535)
        base_cf_port: int = Field(ge=1024, le=65535)
        base_http_port: int = Field(ge=1024, le=65535)
        base_ip: str
        subnet: str
    
    class Build(BaseModel):
        type: str = "debug"
        cellframe_version: str = "latest"
    
    network: Network
    topology: Dict[str, TopologyNode]
    consensus: Consensus
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
    
    def load_topology(self, name: str = "default") -> NetworkTopology:
        """
        Load network topology configuration.
        
        Args:
            name: Topology name (without .json extension)
            
        Returns:
            Validated NetworkTopology object
            
        Raises:
            FileNotFoundError: If topology file doesn't exist
            ValueError: If topology is invalid
        """
        topology_file = self.topologies_dir / f"{name}.json"
        
        if not topology_file.exists():
            logger.error("topology_not_found", topology=name, path=str(topology_file))
            raise FileNotFoundError(f"Topology '{name}' not found at {topology_file}")
        
        logger.info("loading_topology", topology=name)
        
        with open(topology_file) as f:
            data = json.load(f)
        
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

