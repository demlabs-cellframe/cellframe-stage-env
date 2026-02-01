"""
Configuration loader for stage environment.

Handles loading and validation of:
- Stage environment config (stage-env.cfg)
- Network topologies (JSON templates)
- Template configurations (Jinja2)

NOTE: Use config.manager.get_config_loader() to get global ConfigLoader instance.
Direct instantiation of ConfigLoader is deprecated - use global manager instead.
"""

import json
import configparser
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from jinja2 import Environment, FileSystemLoader, Template
from pydantic import BaseModel, Field, field_validator

from src.utils.logger import get_logger

logger = get_logger(__name__)


class NetworkTopology(BaseModel):
    """Network topology configuration."""
    
    class Network(BaseModel):
        name: str
        network_id: str
        consensus: str
        native_ticker: str = "TCELL"
    
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
        new_round_delay: int = Field(ge=1, default=30)
        collecting_level: float = Field(ge=0.0, le=100.0, default=10.0)
        # If None, will be auto-generated as {network_name}.master
        auth_certs_prefix: Optional[str] = None
        # Additional ESBocs timing parameters
        round_start_sync_timeout: int = Field(ge=1, default=5)
        round_attempts_max: int = Field(ge=1, default=2)
        round_attempt_timeout: int = Field(ge=1, default=5)
        consensus_debug: bool = Field(default=True)
    
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
    
    class Timeouts(BaseModel):
        """Timeout configurations in seconds."""
        startup: int = Field(300, ge=30, description="Node startup timeout")
        health_check: int = Field(300, ge=30, description="Health check timeout")
        command: int = Field(30, ge=5, description="CLI command execution timeout")
    
    network: Network
    topology: Dict[str, TopologyNode]
    consensus: Consensus
    balancer: Balancer = Balancer()
    network_settings: NetworkSettings
    build: Build
    features: Dict[str, bool] = {}
    timeouts: Timeouts = Timeouts()
    
    @field_validator("topology")
    @classmethod
    def validate_topology(cls, v):
        """Ensure at least one node type is defined."""
        if not v:
            raise ValueError("Topology must define at least one node type")
        return v


class ConfigLoader:
    """Load and manage stage environment configurations."""
    
    def __init__(self, base_path: Path, config_path: Optional[Path] = None):
        """
        Initialize configuration loader.
        
        Args:
            base_path: Base path to stage-env directory
            config_path: Optional path to stage-env.cfg (overrides default location)
        """
        self.base_path = base_path
        self.config_dir = base_path / "config"
        self.topologies_dir = self.config_dir / "topologies"
        self.templates_dir = self.config_dir / "templates"
        self.custom_config_path = config_path
        
        # Setup Jinja2 environment
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=False,
        )
        
        logger.debug("config_loader_initialized", 
                    base_path=str(base_path),
                    custom_config=str(config_path) if config_path else None)
    
    @property
    def config_path(self) -> Path:
        """Get resolved path to stage-env.cfg."""
        return self.custom_config_path or (self.config_dir / "stage-env.cfg")
    
    def load_stage_config(self) -> Dict[str, Any]:
        """
        Load stage-env configuration file.
        
        Config file must exist explicitly - no auto-creation.
        Use custom config path with ConfigLoader(base_path, config_path) or
        ensure stage-env.cfg exists in config/ directory.
        
        Returns:
            Configuration dictionary with all default values
            
        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        # Use custom config path if provided, otherwise use default
        if self.custom_config_path:
            config_file = self.custom_config_path
        else:
            config_file = self.config_dir / "stage-env.cfg"
        
        # Load config (no auto-creation - config must exist explicitly)
        if not config_file.exists():
            error_msg = f"Configuration file not found: {config_file}"
            if not self.custom_config_path:
                error_msg += f"\n\nDefault config location: {self.config_dir / 'stage-env.cfg'}"
                error_msg += f"\nYou can copy from template: {self.config_dir / 'stage-env.cfg.default'}"
                error_msg += f"\nOr specify custom config with --config option"
            logger.error("config_not_found", path=str(config_file))
            raise FileNotFoundError(error_msg)
        
        config = configparser.ConfigParser()
        config.read(config_file)
        
        logger.info("loaded_config", path=str(config_file))
        
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
        
        # Add aliases for config keys used in topology templates
        # Template uses 'network_name' but config has 'name' in [network] section
        if 'name' in result and 'network_name' not in result:
            result['network_name'] = result['name']
        
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
    
    def load_config_file(self, config_path: Path) -> configparser.ConfigParser:
        """
        Load arbitrary INI-style config file using ConfigParser.
        
        Centralized method for reading config files to ensure consistent behavior.
        Use this instead of directly creating ConfigParser instances.
        
        Args:
            config_path: Path to config file
            
        Returns:
            ConfigParser instance with loaded config
            
        Raises:
            FileNotFoundError: If config file doesn't exist
        """
        if not config_path.exists():
            logger.error("config_file_not_found", path=str(config_path))
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        config = configparser.ConfigParser()
        config.read(config_path)
        logger.debug("config_file_loaded", path=str(config_path), sections=len(config.sections()))
        return config
    
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
    
    def get_timeouts(self) -> Dict[str, int]:
        """
        Load timeout configuration from stage-env.cfg.
        
        Returns:
            Dictionary with timeout values in seconds:
            - startup: Node startup timeout (default: 300s)
            - health_check: Health check timeout (default: 300s)
            - command: CLI command timeout (default: 30s)
        """
        # Use custom config path if provided, otherwise use default
        if self.custom_config_path:
            config_file = self.custom_config_path
        else:
            config_file = self.config_dir / "stage-env.cfg"
        
        # Default timeouts
        timeouts = {
            'startup': 300,
            'health_check': 300,
            'command': 30,
        }
        
        if not config_file.exists():
            logger.warning("config_not_found_using_defaults", path=str(config_file))
            return timeouts
        
        # Load config
        config = configparser.ConfigParser()
        config.read(config_file)
        
        # Read timeouts section if exists
        if config.has_section('timeouts'):
            for key in timeouts.keys():
                if config.has_option('timeouts', key):
                    try:
                        value = config.getint('timeouts', key)
                        if value >= 5:  # Minimum timeout
                            timeouts[key] = value
                        else:
                            logger.warning("timeout_too_small", key=key, value=value, 
                                         minimum=5, using_default=timeouts[key])
                    except ValueError as e:
                        logger.warning("invalid_timeout_value", key=key, error=str(e),
                                      using_default=timeouts[key])
        
        logger.debug("timeouts_loaded", **timeouts)
        return timeouts
    
    def get_paths_config(self) -> Dict[str, str]:
        """
        Load paths configuration from stage-env.cfg.
        
        Returns:
            Dictionary with path values:
            - cache_dir: Cache directory path (default: cache)
            - artifacts_dir: Artifacts directory path (default: artifacts)
        """
        # Use custom config path if provided, otherwise use default
        if self.custom_config_path:
            config_file = self.custom_config_path
            logger.debug("using_custom_config_path", path=str(config_file))
        else:
            config_file = self.config_dir / "stage-env.cfg"
            logger.debug("using_default_config_path", path=str(config_file))
        
        # Default paths
        paths = {
            'cache_dir': 'cache',
            'artifacts_dir': 'artifacts',
        }
        
        if not config_file.exists():
            logger.warning("config_not_found_using_defaults", 
                         path=str(config_file),
                         custom_config_path=str(self.custom_config_path) if self.custom_config_path else None)
            return paths
        
        # Load config
        config = configparser.ConfigParser()
        config.read(config_file)
        
        # Read paths section if exists
        if config.has_section('paths'):
            for key in paths.keys():
                if config.has_option('paths', key):
                    paths[key] = config.get('paths', key)
        
        logger.debug("paths_loaded", **paths)
        return paths
    
    def get_artifacts_config(self) -> Dict[str, any]:
        """
        Load artifacts configuration from stage-env.cfg.
        
        Returns:
            Dictionary with artifacts configuration
        """
        # Use custom config path if provided, otherwise use default
        if self.custom_config_path:
            config_file = self.custom_config_path
        else:
            config_file = self.config_dir / "stage-env.cfg"
        
        # Default artifacts config
        artifacts = {
            'collect_node_logs': True,
            'collect_health_logs': True,
            'collect_crash_dumps': True,
            'retain_days': 30,
        }
        
        if not config_file.exists():
            logger.warning("config_not_found_using_defaults", path=str(config_file))
            return artifacts
        
        # Load config
        config = configparser.ConfigParser()
        config.read(config_file)
        
        # Read artifacts section if exists
        if config.has_section('artifacts'):
            if config.has_option('artifacts', 'collect_node_logs'):
                artifacts['collect_node_logs'] = config.getboolean('artifacts', 'collect_node_logs')
            if config.has_option('artifacts', 'collect_health_logs'):
                artifacts['collect_health_logs'] = config.getboolean('artifacts', 'collect_health_logs')
            if config.has_option('artifacts', 'collect_crash_dumps'):
                artifacts['collect_crash_dumps'] = config.getboolean('artifacts', 'collect_crash_dumps')
            if config.has_option('artifacts', 'retain_days'):
                artifacts['retain_days'] = config.getint('artifacts', 'retain_days')
        
        # Also get artifacts_dir from [paths] section
        if config.has_section('paths') and config.has_option('paths', 'artifacts_dir'):
            artifacts['artifacts_dir'] = config.get('paths', 'artifacts_dir')
        else:
            artifacts['artifacts_dir'] = '../testing/artifacts'
        
        logger.debug("artifacts_config_loaded", **artifacts)
        return artifacts
    
    def get_logging_config(self) -> Dict[str, any]:
        """
        Load logging configuration from stage-env.cfg.
        
        Returns:
            Dictionary with logging configuration
        """
        # Use custom config path if provided, otherwise use default
        if self.custom_config_path:
            config_file = self.custom_config_path
        else:
            config_file = self.config_dir / "stage-env.cfg"
        
        # Default logging config
        logging = {
            'log_dir': 'logs',
            'log_level': 'info',
            'scenario_logs': True,
            'retain_days': 7,
        }
        
        if not config_file.exists():
            logger.warning("config_not_found_using_defaults", path=str(config_file))
            return logging
        
        # Load config
        config = configparser.ConfigParser()
        config.read(config_file)
        
        # Read logging section if exists
        if config.has_section('logging'):
            if config.has_option('logging', 'log_dir'):
                logging['log_dir'] = config.get('logging', 'log_dir')
            if config.has_option('logging', 'log_level'):
                logging['log_level'] = config.get('logging', 'log_level')
            if config.has_option('logging', 'scenario_logs'):
                logging['scenario_logs'] = config.getboolean('logging', 'scenario_logs')
            if config.has_option('logging', 'retain_days'):
                logging['retain_days'] = config.getint('logging', 'retain_days')
        
        logger.debug("logging_config_loaded", **logging)
        return logging
    
    def get_scenarios_config(self) -> Dict[str, any]:
        """
        Load scenarios configuration from stage-env.cfg.
        
        Returns:
            Dictionary with scenarios configuration:
            - debug: Enable detailed extraction/validation debug output (default: False)
        """
        # Use custom config path if provided, otherwise use default
        if self.custom_config_path:
            config_file = self.custom_config_path
        else:
            config_file = self.config_dir / "stage-env.cfg"
        
        # Default scenarios config
        scenarios = {
            'debug': False,
        }
        
        if not config_file.exists():
            logger.warning("config_not_found_using_defaults", path=str(config_file))
            return scenarios
        
        # Load config
        config = configparser.ConfigParser()
        config.read(config_file)
        
        # Read scenarios section if exists
        if config.has_section('scenarios'):
            if config.has_option('scenarios', 'debug'):
                scenarios['debug'] = config.getboolean('scenarios', 'debug')
        
        logger.debug("scenarios_config_loaded", **scenarios)
        return scenarios
    
    def get_suite_isolation_config(self) -> Dict[str, Any]:
        """
        Load suite isolation (snapshot) configuration from stage-env.cfg.
        
        Returns:
            Dictionary with suite isolation configuration:
            - mode: Snapshot mode (disabled/recreate/filesystem/squashfs)
            - squashfs_compression: Compression for squashfs mode
            - auto_create_on_startup: Auto-create snapshot after network start
            - snapshot_name: Name of snapshot to use for suite isolation
            - auto_cleanup: Automatically cleanup old snapshots
            - keep_snapshot_count: Number of snapshots to keep
            - snapshots_dir: Directory for storing snapshots
        """
        # Use custom config path if provided, otherwise use default
        if self.custom_config_path:
            config_file = self.custom_config_path
        else:
            config_file = self.config_dir / "stage-env.cfg"
        
        # Default configuration
        suite_isolation = {
            'mode': 'filesystem',
            'squashfs_compression': 'none',
            'auto_create_on_startup': True,
            'snapshot_name': 'clean_state',
            'genesis_stage': 'full',
            'phase1_snapshot_name': 'phase1_zerochain_genesis',
            'auto_cleanup': True,
            'keep_snapshot_count': 5,
            'snapshots_dir': '../testing/snapshots',
        }
        
        if not config_file.exists():
            logger.warning("config_not_found_using_defaults", path=str(config_file))
            return suite_isolation
        
        # Load config
        config = configparser.ConfigParser()
        config.read(config_file)
        
        # Read suite_isolation section if exists
        if config.has_section('suite_isolation'):
            if config.has_option('suite_isolation', 'mode'):
                suite_isolation['mode'] = config.get('suite_isolation', 'mode')
            if config.has_option('suite_isolation', 'squashfs_compression'):
                suite_isolation['squashfs_compression'] = config.get('suite_isolation', 'squashfs_compression')
            if config.has_option('suite_isolation', 'auto_create_on_startup'):
                suite_isolation['auto_create_on_startup'] = config.getboolean('suite_isolation', 'auto_create_on_startup')
            if config.has_option('suite_isolation', 'snapshot_name'):
                suite_isolation['snapshot_name'] = config.get('suite_isolation', 'snapshot_name')
            if config.has_option('suite_isolation', 'genesis_stage'):
                suite_isolation['genesis_stage'] = config.get('suite_isolation', 'genesis_stage')
            if config.has_option('suite_isolation', 'phase1_snapshot_name'):
                suite_isolation['phase1_snapshot_name'] = config.get('suite_isolation', 'phase1_snapshot_name')
            if config.has_option('suite_isolation', 'auto_cleanup'):
                suite_isolation['auto_cleanup'] = config.getboolean('suite_isolation', 'auto_cleanup')
            if config.has_option('suite_isolation', 'keep_snapshot_count'):
                suite_isolation['keep_snapshot_count'] = config.getint('suite_isolation', 'keep_snapshot_count')
            if config.has_option('suite_isolation', 'snapshots_dir'):
                suite_isolation['snapshots_dir'] = config.get('suite_isolation', 'snapshots_dir')
        
        logger.debug("suite_isolation_config_loaded", **suite_isolation)
        return suite_isolation
    
    def get_scenarios_config(self) -> Dict:
        """Get scenarios execution configuration."""
        config_file = self.custom_config_path or (self.config_dir / "stage-env.cfg")
        
        if not config_file.exists():
            return {'debug': False}
        
        config = configparser.ConfigParser()
        config.read(config_file)
        
        if 'scenarios' not in config:
            return {'debug': False}
        
        return {
            'debug': config.getboolean('scenarios', 'debug', fallback=False)
        }
    
    def get_node_source_config(self) -> Dict[str, Any]:
        """
        Load node_source configuration from stage-env.cfg.
        
        Source types:
            - url: Download .deb from URL (default)
            - local: Use specific .deb from local_path
            - build: Auto-detect .deb from project's test_build/ directory
            - repository: Build from git inside container
        
        Returns:
            Dict with node_source configuration (type, url, local_path, etc.)
        """
        node_source = {
            'type': 'url',  # Default: download from URL
            'url': None,
            'local_path': None,
            'repository_url': None,
            'repository_branch': 'master',
            'build_type': 'debug',
            'checksum': None,
            'headers': None,
            'build_dir': None,  # For type=build: path to test_build/
        }
        
        config_file = self.custom_config_path or (self.config_dir / "stage-env.cfg")
        
        if not config_file.exists():
            logger.warning("config_not_found_using_defaults", path=str(config_file))
            return node_source
        
        # Load config
        config = configparser.ConfigParser()
        config.read(config_file)
        
        # Read node_source section if exists
        if config.has_section('node_source'):
            if config.has_option('node_source', 'type'):
                node_source['type'] = config.get('node_source', 'type')
            if config.has_option('node_source', 'url'):
                node_source['url'] = config.get('node_source', 'url')
            if config.has_option('node_source', 'local_path'):
                node_source['local_path'] = config.get('node_source', 'local_path')
            if config.has_option('node_source', 'repository_url'):
                node_source['repository_url'] = config.get('node_source', 'repository_url')
            if config.has_option('node_source', 'branch'):
                node_source['repository_branch'] = config.get('node_source', 'branch')
            if config.has_option('node_source', 'build_type'):
                node_source['build_type'] = config.get('node_source', 'build_type')
            if config.has_option('node_source', 'checksum'):
                node_source['checksum'] = config.get('node_source', 'checksum')
            if config.has_option('node_source', 'headers'):
                node_source['headers'] = config.get('node_source', 'headers')
            if config.has_option('node_source', 'build_dir'):
                node_source['build_dir'] = config.get('node_source', 'build_dir')
        
        # Handle type=build: auto-detect .deb from project's test_build/
        if node_source['type'] == 'build':
            node_source = self._resolve_build_source(node_source)
        
        logger.debug("node_source_config_loaded", **node_source)
        return node_source
    
    def _resolve_build_source(self, node_source: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve type=build to find the latest .deb in test_build/ directory.
        
        Searches in order:
        1. Explicit build_dir from config
        2. ../test_build/ (relative to stage-env)
        3. ../../test_build/ (if stage-env is in tests/)
        """
        from pathlib import Path
        import glob
        
        build_dir = None
        
        # Try explicit build_dir
        if node_source.get('build_dir'):
            build_dir = Path(node_source['build_dir']).expanduser().resolve()
        
        # Try relative paths from stage-env directory
        if not build_dir or not build_dir.exists():
            # stage-env is typically in cellframe-node/tests/stage-env/
            # test_build is in cellframe-node/test_build/
            candidates = [
                self.config_dir.parent.parent / "test_build",  # ../../test_build
                self.config_dir.parent / "test_build",          # ../test_build
                Path.cwd() / "test_build",                      # ./test_build
            ]
            for candidate in candidates:
                if candidate.exists():
                    build_dir = candidate.resolve()
                    break
        
        if not build_dir or not build_dir.exists():
            logger.warning("build_dir_not_found", 
                          msg="type=build specified but test_build/ not found. Falling back to url.")
            node_source['type'] = 'url'
            return node_source
        
        # Find latest .deb file
        deb_files = list(build_dir.glob("cellframe-node-*.deb"))
        if not deb_files:
            logger.warning("no_deb_in_build_dir", 
                          build_dir=str(build_dir),
                          msg="No .deb files found. Falling back to url.")
            node_source['type'] = 'url'
            return node_source
        
        # Sort by modification time, get the latest
        latest_deb = max(deb_files, key=lambda p: p.stat().st_mtime)
        
        # Convert to 'local' type with auto-detected path
        node_source['type'] = 'local'
        node_source['local_path'] = str(latest_deb)
        node_source['build_dir'] = str(build_dir)
        
        logger.info("build_source_resolved", 
                   deb_file=latest_deb.name, 
                   build_dir=str(build_dir))
        
        return node_source
    
    def get_node_version(self) -> Optional[str]:
        """
        Extract version from the node package name.
        
        Package name formats:
        - cellframe-node-6.0-LOCALBUILD1-dbg-amd64.deb -> "6.0"
        - cellframe-node-5.2.123-amd64.deb -> "5.2"
        - cellframe-node-latest.deb -> None (unknown)
        
        Returns:
            Major.minor version string (e.g., "6.0", "5.2") or None if unknown
        """
        import re
        
        node_source = self.get_node_source_config()
        local_path = node_source.get('local_path')
        
        if not local_path:
            logger.debug("no_local_path_for_version_detection")
            return None
        
        # Extract filename from path
        package_name = Path(local_path).name
        
        # Pattern: cellframe-node-X.Y... where X.Y is major.minor
        # Examples:
        #   cellframe-node-6.0-LOCALBUILD1-dbg-amd64.deb
        #   cellframe-node-5.2.345-amd64.deb
        #   cellframe-node-5.0-amd64.deb
        match = re.search(r'cellframe-node-(\d+\.\d+)', package_name)
        
        if match:
            version = match.group(1)
            logger.info("node_version_detected", 
                       package_name=package_name, 
                       version=version)
            return version
        
        logger.warning("could_not_detect_version_from_package",
                      package_name=package_name)
        return None
    
    def get_genesis_scenario_path(self, scenario_name: str) -> str:
        """
        Get path to genesis scenario based on detected node version.
        
        Search order:
        1. Version-specific path: genesis/{detected_version}/{scenario_name}
        2. Default path: genesis/{scenario_name}  
        3. Auto-detect: find any version subdirectory with the scenario
        
        Args:
            scenario_name: Scenario filename (e.g., "phase1_zerochain.yml")
            
        Returns:
            Path relative to scenarios directory (e.g., "genesis/6.0/phase1_zerochain.yml")
            
        Raises:
            FileNotFoundError: If scenario not found in any location
        """
        # scenarios/ is at stage-env root level, not under config/
        # config_dir is stage-env/config/, so go up one level
        stage_env_dir = self.config_dir.parent
        scenarios_dir = stage_env_dir / "scenarios"
        genesis_dir = scenarios_dir / "genesis"
        
        version = self.get_node_version()
        
        # 1. Try version-specific path first
        if version:
            version_path = f"genesis/{version}/{scenario_name}"
            full_path = scenarios_dir / version_path
            
            if full_path.exists():
                logger.info("using_version_specific_genesis_scenario",
                          version=version,
                          scenario=version_path)
                return version_path
            else:
                logger.warning("version_specific_scenario_not_found",
                             version=version,
                             scenario=scenario_name,
                             tried_path=str(full_path))
        
        # 2. Try default path (genesis/{scenario_name})
        default_path = f"genesis/{scenario_name}"
        if (scenarios_dir / default_path).exists():
            logger.info("using_default_genesis_scenario", scenario=default_path)
            return default_path
        
        # 3. Auto-detect: find any version subdirectory with the scenario
        if genesis_dir.exists():
            # Get version subdirectories (e.g., "5.0", "6.0")
            version_dirs = sorted(
                [d for d in genesis_dir.iterdir() 
                 if d.is_dir() and d.name[0].isdigit()],
                key=lambda d: d.name,
                reverse=True  # Prefer newest version
            )
            
            for ver_dir in version_dirs:
                candidate = ver_dir / scenario_name
                if candidate.exists():
                    found_path = f"genesis/{ver_dir.name}/{scenario_name}"
                    logger.warning("auto_detected_genesis_scenario",
                                 detected_version=ver_dir.name,
                                 scenario=found_path,
                                 note="Version not detected from package, using auto-detected scenario")
                    return found_path
        
        # No scenario found anywhere
        available_versions = []
        if genesis_dir.exists():
            available_versions = [d.name for d in genesis_dir.iterdir() 
                                 if d.is_dir() and d.name[0].isdigit()]
        
        raise FileNotFoundError(
            f"Genesis scenario '{scenario_name}' not found. "
            f"Detected version: {version or 'unknown'}. "
            f"Available version directories: {available_versions or 'none'}. "
            f"Searched paths: genesis/{version}/{scenario_name}, genesis/{scenario_name}"
        )

