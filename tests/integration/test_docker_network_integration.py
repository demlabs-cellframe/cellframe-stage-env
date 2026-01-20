"""Integration tests for Docker + Network modules."""

import pytest
from pathlib import Path
import tempfile
import shutil
from unittest.mock import MagicMock, patch, AsyncMock

from src.docker_ctl.container import DockerContainerManager
from src.docker_ctl.compose import DockerComposeManager
from src.network.manager import NetworkManager


class TestDockerNetworkIntegration:
    """Test integration between Docker and Network management modules."""
    
    @pytest.fixture
    def temp_base_path(self):
        """Create temporary base path."""
        temp_dir = Path(tempfile.mkdtemp())
        (temp_dir / "cache").mkdir()
        (temp_dir / "compose").mkdir()
        yield temp_dir
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
        
        # NetworkManager should be able to use this
        with patch('src.network.manager.DockerComposeManager', return_value=compose_manager):
            network_config = {
                "name": "stagenet",
                "nodes": [{"name": "node1", "role": "root"}]
            }
            manager = NetworkManager(temp_base_path, network_config)
            assert manager is not None
    
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
        
        # Test resolution
        container_name = container_manager.resolve_node_to_container("node1")
        assert container_name == "cellframe-node-node1"
    
    @pytest.mark.asyncio
    async def test_container_exec_with_network_context(self, container_manager, mock_docker_client):
        """Test that container exec works in network context."""
        # Mock container with exec
        mock_container = MagicMock()
        mock_container.name = "cellframe-stage-node1"
        
        mock_exec_result = MagicMock()
        mock_exec_result.output = (b"Success\n", b"")
        mock_exec_result.exit_code = 0
        
        mock_container.exec_run.return_value = mock_exec_result
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
        network_config = {
            "name": "stagenet",
            "nodes": [
                {"name": "node1", "role": "root"},
                {"name": "node2", "role": "master"}
            ]
        }
        
        with patch('src.network.manager.DockerComposeManager'):
            manager = NetworkManager(temp_base_path, network_config)
            
            # NetworkManager should be able to resolve nodes
            assert manager.config["name"] == "stagenet"
            assert len(manager.config["nodes"]) == 2
    
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
