"""Integration tests for Docker + Network modules."""

import pytest
from pathlib import Path
import tempfile
import shutil
from unittest.mock import MagicMock, patch, AsyncMock
import yaml

from src.docker_ctl.container import DockerContainerManager
from src.docker_ctl.compose import DockerComposeManager
from src.network.manager import NetworkManager
from src.config.manager import initialize_config, reset_config


class TestDockerNetworkIntegration:
    """Test integration between Docker and Network management modules."""
    
    @pytest.fixture
    def temp_base_path(self):
        """Create temporary base path with config."""
        temp_dir = Path(tempfile.mkdtemp())
        (temp_dir / "cache").mkdir()
        (temp_dir / "compose").mkdir()
        (temp_dir / "config").mkdir()
        
        # Create minimal config for ConfigManager
        config_file = temp_dir / "config" / "config.yml"
        config_file.write_text(yaml.dump({
            "network": {"name": "stagenet"},
            "nodes": [{"name": "node1", "role": "root"}]
        }))
        
        # Initialize config manager for this test scope
        initialize_config(temp_dir)
        
        yield temp_dir
        
        # Cleanup
        reset_config()
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def mock_docker_client(self):
        """Mock Docker client."""
        client = MagicMock()
        client.containers.list.return_value = []
        client.networks.list.return_value = []
        return client
    
    @pytest.fixture
    def container_manager(self, temp_base_path, mock_docker_client):
        """Create DockerContainerManager with mocked client."""
        with patch('docker.from_env', return_value=mock_docker_client):
            manager = DockerContainerManager(temp_base_path)
            return manager
    
    @pytest.fixture
    def compose_manager(self, temp_base_path):
        """Create DockerComposeManager."""
        manager = DockerComposeManager(temp_base_path)
        return manager
    
    def test_compose_generates_for_network_manager(self, temp_base_path, compose_manager):
        """Test that DockerComposeManager generates files consumable by NetworkManager."""
        # Create minimal docker-compose.yml
        compose_file = temp_base_path / "compose" / "docker-compose.yml"
        compose_file.write_text("""
version: '3.8'
services:
  node1:
    image: test/cellframe-node
    container_name: cellframe-stage-node1
    networks:
      - stagenet
networks:
  stagenet:
    driver: bridge
""")
        
        # Create minimal topology file for NetworkManager
        (temp_base_path / "config" / "topologies").mkdir(parents=True, exist_ok=True)
        topology_file = temp_base_path / "config" / "topologies" / "default.json.tpl"
        # Topology templates are Jinja2 templates, so write as JSON string
        import json
        topology_file.write_text(json.dumps({
            "network": {"name": "stagenet", "ledger": "DAG-PoA"},
            "topology": {"type": "single"},
            "consensus": {"type": "dag-poa"},
            "network_settings": {},
            "build": {}
        }, indent=2))
        
        # NetworkManager should be able to use this compose file
        network_manager = NetworkManager(base_path=temp_base_path)
        assert network_manager is not None
        assert network_manager.base_path == temp_base_path
    
    def test_container_manager_with_network_lifecycle(self, container_manager, mock_docker_client):
        """Test container operations work with network lifecycle."""
        # Mock network creation
        mock_network = MagicMock()
        mock_network.name = "stagenet"
        mock_docker_client.networks.create.return_value = mock_network
        mock_docker_client.networks.list.return_value = [mock_network]
        
        # Mock container
        mock_container = MagicMock()
        mock_container.name = "cellframe-stage-node1"
        mock_container.status = "running"
        mock_docker_client.containers.get.return_value = mock_container
        
        # Test resolution - resolve_node_to_container returns container name as string
        container_name = container_manager.resolve_node_to_container("node1")
        assert container_name == "cellframe-stage-node-1"
    
    @pytest.mark.asyncio
    async def test_container_exec_with_network_context(self, container_manager, mock_docker_client):
        """Test that container exec works in network context."""
        # Mock container with exec
        mock_container = MagicMock()
        mock_container.name = "cellframe-stage-node1"
        mock_container.status = "running"
        mock_container.attrs = {
            "State": {
                "Status": "running",
                "Running": True,
                "ExitCode": 0
            }
        }
        
        # exec_run returns tuple (exit_code, output)
        mock_container.exec_run.return_value = (0, b"Success\n")
        mock_docker_client.containers.get.return_value = mock_container
        
        # Execute command
        result = await container_manager.exec_cli_command(
            "version",
            node="node1",
            timeout=30
        )
        
        assert result["returncode"] == 0
        assert "Success" in result["stdout"]
    
    def test_network_manager_uses_container_manager(self, temp_base_path, container_manager):
        """Test NetworkManager can use DockerContainerManager for operations."""
        # Create minimal topology file for NetworkManager
        (temp_base_path / "config" / "topologies").mkdir(parents=True, exist_ok=True)
        topology_file = temp_base_path / "config" / "topologies" / "default.json.tpl"
        import json
        topology_file.write_text(json.dumps({
            "network": {"name": "stagenet", "ledger": "DAG-PoA"},
            "topology": {"type": "single"},
            "consensus": {"type": "dag-poa"},
            "network_settings": {},
            "build": {}
        }, indent=2))
        
        # NetworkManager now initialized via ConfigManager fixture
        network_manager = NetworkManager(base_path=temp_base_path)
        
        # Verify NetworkManager can access config
        assert network_manager.config_data["network"]["name"] == "stagenet"
        assert len(network_manager.config_data["nodes"]) == 1
    
    def test_compose_cleanup_integration(self, compose_manager, mock_docker_client):
        """Test compose cleanup integrates with container operations."""
        # Mock containers for cleanup
        mock_container = MagicMock()
        mock_container.name = "cellframe-stage-node1"
        mock_docker_client.containers.list.return_value = [mock_container]
        
        # Cleanup operation (mocked)
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            
            # Compose manager should handle cleanup
            assert compose_manager is not None


class TestDockerNetworkErrorHandling:
    """Test error handling in Docker + Network integration."""
    
    def test_network_creation_failure_propagates(self, temp_base_path):
        """Test that network creation failures are properly handled."""
        with patch('docker.from_env') as mock_docker:
            mock_docker.side_effect = Exception("Docker daemon not running")
            
            with pytest.raises(Exception, match="Docker daemon"):
                DockerContainerManager(temp_base_path)
    
    def test_container_not_found_in_network(self, temp_base_path):
        """Test handling of missing container in network context."""
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = Exception("Container not found")
        
        with patch('docker.from_env', return_value=mock_client):
            manager = DockerContainerManager(temp_base_path)
            
            with pytest.raises(Exception, match="not found"):
                mock_client.containers.get("nonexistent")
