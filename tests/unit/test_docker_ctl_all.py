"""Unit tests for src/docker_ctl/ modules."""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestDockerContainer:
    """Test DockerContainerManager."""
    
    def test_container_manager_import(self):
        from src.docker_ctl.container import DockerContainerManager
        assert DockerContainerManager is not None


class TestDockerCompose:
    """Test DockerComposeManager."""
    
    def test_compose_manager_import(self):
        from src.docker_ctl.compose import DockerComposeManager
        assert DockerComposeManager is not None


class TestDockerIntegration:
    """Integration tests."""
    
    def test_docker_modules_importable(self):
        from src.docker_ctl import container, compose
        assert all([container, compose])
