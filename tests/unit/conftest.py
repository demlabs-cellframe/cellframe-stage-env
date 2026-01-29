"""Unit test fixtures."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path
import sys

# Ensure stage-env root is in path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.docker.container import DockerContainerManager

@pytest.fixture
def mock_docker_client():
    """Mock Docker client."""
    client = MagicMock()
    # Mock containers.list to return empty list by default
    client.containers.list.return_value = []
    # Mock containers.run
    client.containers.run.return_value = b"Success"
    return client

@pytest.fixture
def mock_container_manager(mock_docker_client):
    """Mock DockerContainerManager."""
    manager = MagicMock(spec=DockerContainerManager)
    manager.docker_client = mock_docker_client
    
    # Mock exec_cli_command
    async def mock_exec(command, node, timeout=30):
        return {
            "returncode": 0,
            "stdout": "Success",
            "stderr": ""
        }
    manager.exec_cli_command = AsyncMock(side_effect=mock_exec)
    
    # Mock resolve_node_to_container
    manager.resolve_node_to_container.side_effect = lambda n: f"cellframe-node-{n}"
    
    return manager

@pytest.fixture
def sample_yaml_error():
    """Sample YAML error response."""
    return """
errors:
  code: 102
  message: "Wallet not found"
"""

@pytest.fixture
def sample_yaml_success():
    """Sample YAML success response."""
    return """
status: success
data:
  value: 100
"""

@pytest.fixture
def cli_help_main():
    """Sample CLI main help output."""
    return """
Cellframe Node CLI tool

Commands:
    version:                    Show version
    help:                       Show help
    exit:                       Exit
    token_decl:                 Token declaration
    token_emit:                 Token emission
    wallet:                     Wallet operations
    tx_create:                  Create transaction
"""

@pytest.fixture
def cli_help_token_decl():
    """Sample CLI token_decl help output."""
    return """
token_decl - Token declaration

Options:
    -net <net_name>             Network name
    -chain <chain_name>         Chain name
    -token <token_ticker>       Token ticker
    -total_supply <value>       Total supply
    -signs_total <value>        Total signs
    -certs <certs_list>         Certificates list
    -flags <flags_list>         Flags list
    -decimals <value>           Decimals
"""
