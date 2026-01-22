"""Pytest configuration for unit tests."""

import sys
import os
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

# Add stage-env root to Python path
STAGE_ENV_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(STAGE_ENV_ROOT))

# Import mocks
sys.path.insert(0, str(Path(__file__).parent.parent))
from mocks import create_mock_docker_client, create_mock_container


# ============================================================================
# Docker Mocks
# ============================================================================

@pytest.fixture
def mock_docker_client():
    """Provide a mock Docker client."""
    return create_mock_docker_client()


@pytest.fixture
def mock_container():
    """Provide a mock Docker container."""
    return create_mock_container()


@pytest.fixture
def mock_container_manager(mock_docker_client):
    """Provide a mock DockerContainerManager."""
    with patch("src.docker_ctl.container.docker") as mock_docker:
        mock_docker.from_env.return_value = mock_docker_client
        
        from src.docker_ctl.container import DockerContainerManager
        
        manager = DockerContainerManager()
        manager.client = mock_docker_client
        
        # Setup async mock for exec_cli_command
        manager.exec_cli_command = AsyncMock(return_value={
            "returncode": 0,
            "stdout": "Mock CLI output",
            "stderr": ""
        })
        
        return manager


# ============================================================================
# CLI Fixtures
# ============================================================================

@pytest.fixture
def cli_help_main(fixtures_dir):
    """Load main CLI help output."""
    return (fixtures_dir / "cli_help_main.txt").read_text()


@pytest.fixture
def cli_help_token_decl(fixtures_dir):
    """Load token_decl CLI help output."""
    return (fixtures_dir / "cli_help_token_decl.txt").read_text()


# ============================================================================
# YAML Response Fixtures
# ============================================================================

@pytest.fixture
def sample_yaml_error():
    """Sample YAML error response from CLI."""
    return """
errors:
  code: 102
  message: Token already exists
"""


@pytest.fixture
def sample_yaml_success():
    """Sample YAML success response from CLI."""
    return """
hash: 0x1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF
status: success
message: Operation completed
"""


# ============================================================================
# Config & Topology Fixtures
# ============================================================================

@pytest.fixture
def sample_topology_config():
    """Sample network topology configuration."""
    return {
        "network": {
            "name": "testnet",
            "network_id": "0x1",
            "consensus": "poa"
        },
        "topology": {
            "root": {"count": 3, "role": "root", "is_seed_node": True},
            "master": {"count": 3, "role": "master", "consensus_participation": True},
            "full": {"count": 2, "role": "full"}
        },
        "consensus": {
            "type": "poa",
            "min_validators": 3,
            "new_round_delay": 100,
            "collecting_level": 50.0,
            "auth_certs_prefix": "testnet.root"
        },
        "network_settings": {
            "base_rpc_port": 8000,
            "base_p2p_port": 8001,
            "base_cf_port": 8002,
            "base_http_port": 8003,
            "base_ip": "10.0.0.1",
            "subnet": "10.0.0.0/24"
        },
        "build": {
            "type": "debug"
        }
    }


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create a temporary config directory structure."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    
    # Create template dirs
    templates_dir = config_dir / "templates"
    (templates_dir / "base").mkdir(parents=True)
    (templates_dir / "cellframe-node.cfg.d").mkdir(parents=True)
    (templates_dir / "chains").mkdir(parents=True)
    
    # Create dummy templates
    (templates_dir / "testnet.cfg.j2").write_text("[general]\nnetwork={{ network_name }}")
    (templates_dir / "base" / "cellframe-node.cfg.j2").write_text("[server]\nip={{ node_ip }}")
    (templates_dir / "chains" / "main.cfg.j2").write_text("[chain]\nname=main")
    
    return config_dir


# ============================================================================
# Network & Node Fixtures
# ============================================================================

@pytest.fixture
def mock_node_config():
    """Provide a mock NodeConfig."""
    from src.network.models import NodeConfig
    
    return NodeConfig(
        node_id=1,
        role="root",
        ip_address="10.0.0.1",
        is_seed_node=True,
        node_type="root",
        rpc_port=8000,
        p2p_port=8001,
        cf_port=8002,
        http_port=8003
    )


@pytest.fixture
def mock_network_topology(sample_topology_config):
    """Provide a mock NetworkTopology."""
    from src.config.loader import NetworkTopology
    
    return NetworkTopology(**sample_topology_config)


# ============================================================================
# Scenario & Step Fixtures
# ============================================================================

@pytest.fixture
def sample_cli_step():
    """Provide a sample CLI step."""
    from src.scenarios.schema import CLIStep
    
    return CLIStep(
        cli="version",
        node="node1",
        timeout=30
    )


@pytest.fixture
def sample_scenario():
    """Provide a sample test scenario."""
    from src.scenarios.schema import ScenarioDefinition, CLIStep

    return ScenarioDefinition(
        name="Sample Test",
        description="A sample test scenario",
        test=[
            CLIStep(cli="version", node="node1")
        ]
    )


@pytest.fixture
def sample_runtime_context(sample_scenario):
    """Provide a sample RuntimeContext."""
    from src.scenarios.executor import RuntimeContext
    
    return RuntimeContext(sample_scenario)


# ============================================================================
# File System Fixtures
# ============================================================================

@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    # Create common directories
    (workspace / "configs").mkdir()
    (workspace / "data").mkdir()
    (workspace / "logs").mkdir()
    (workspace / "certs").mkdir()
    
    return workspace


# ============================================================================
# Monitoring Fixtures
# ============================================================================

@pytest.fixture
def mock_health_checker():
    """Provide a mock HealthChecker."""
    from src.monitoring.health import NodeHealthChecker
    
    checker = MagicMock(spec=NodeHealthChecker)
    checker.check_node_health = AsyncMock(return_value={
        "node": "node1",
        "healthy": True,
        "status": "running"
    })
    
    return checker


@pytest.fixture
def mock_datum_monitor():
    """Provide a mock DatumMonitor."""
    from src.monitoring.datum import DatumMonitor, DatumStatus
    
    monitor = MagicMock(spec=DatumMonitor)
    monitor.wait_for_datum = AsyncMock(return_value=MagicMock(
        status=DatumStatus.ACCEPTED,
        datum_hash="0xABCDEF",
        error_message=None
    ))
    
    return monitor


# ============================================================================
# Utility Fixtures
# ============================================================================

@pytest.fixture
def mock_logger():
    """Provide a mock logger."""
    return MagicMock()


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singleton instances between tests."""
    # Add any singleton cleanup here
    yield
    # Cleanup after test
    pass


# ============================================================================
# Marks & Parametrization
# ============================================================================

def pytest_configure(config):
    """Configure pytest with custom settings."""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test (fast, isolated)"
    )
