"""Unit tests for src/docker_ctl/compose.py."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

class TestDockerComposeManager:
    """Test DockerComposeManager."""
    
    @patch('docker.from_env')
    def test_init(self, mock_docker, tmp_path):
        """Test DockerComposeManager initialization."""
        from src.docker_ctl.compose import DockerComposeManager
        mock_docker.return_value = MagicMock()
        manager = DockerComposeManager(tmp_path / "stage-env")
        assert manager is not None
