"""Unit tests for src/docker_ctl/container.py."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

@patch('docker.from_env')
class TestDockerContainerManager:
    """Test DockerContainerManager."""
    
    def test_init(self, mock_docker, tmp_path):
        """Test DockerContainerManager initialization."""
        from src.docker_ctl.container import DockerContainerManager
        mock_docker.return_value = MagicMock()
        manager = DockerContainerManager(tmp_path / "stage-env")
        assert manager is not None
    
    def test_resolve_node_to_container(self, mock_docker, tmp_path):
        """Test resolving node ID to container name."""
        from src.docker_ctl.container import DockerContainerManager
        mock_docker.return_value = MagicMock()
        manager = DockerContainerManager(tmp_path / "stage-env")
        result = manager.resolve_node_to_container("node1")
        assert isinstance(result, str)
