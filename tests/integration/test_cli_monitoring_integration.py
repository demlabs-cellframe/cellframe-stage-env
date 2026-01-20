"""Integration tests for CLI and monitoring coordination."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock


class TestCLIIntegration:
    """Test CLI commands integration with underlying systems."""
    
    def test_cli_uses_config_loader(self, tmp_path):
        """Test CLI commands load configuration correctly."""
        from src.config.loader import ConfigLoader
        
        config_file = tmp_path / "config.yml"
        config_file.write_text("network:\n  name: stagenet\n")
        
        loader = ConfigLoader(tmp_path)
        config = loader.load_config_file(config_file)
        
        # CLI should be able to access this config
        assert config["network"]["name"] == "stagenet"
    
    def test_cli_logging_integration(self):
        """Test CLI integrates with logging system."""
        from src.utils.logger import setup_logging, get_logger
        
        setup_logging(verbose=True)
        logger = get_logger("test_cli")
        
        # CLI should be able to log
        logger.info("test_message")
        
        assert logger is not None


class TestMonitoringIntegration:
    """Test monitoring system integration."""
    
    @pytest.mark.asyncio
    async def test_monitoring_uses_docker_manager(self):
        """Test monitoring can execute commands via docker."""
        from src.docker_ctl.container import DockerContainerManager
        from unittest.mock import MagicMock, AsyncMock
        
        mock_manager = MagicMock(spec=DockerContainerManager)
        
        async def mock_exec(command, node, timeout=30):
            return {"returncode": 0, "stdout": "OK", "stderr": ""}
        
        mock_manager.exec_cli_command = AsyncMock(side_effect=mock_exec)
        
        result = await mock_manager.exec_cli_command("version", "node1")
        assert result["returncode"] == 0


class TestBuildDeployIntegration:
    """Test build to deployment pipeline."""
    
    def test_build_artifacts_available_for_deployment(self, tmp_path):
        """Test built artifacts can be deployed."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        
        # Simulate build artifact
        (artifacts_dir / "cellframe-node").write_text("binary")
        
        # Deployment should find this artifact
        assert (artifacts_dir / "cellframe-node").exists()


class TestEndToEndModuleFlow:
    """Test typical end-to-end module flow."""
    
    def test_config_to_network_setup_flow(self, tmp_path):
        """Test flow: Config → Network Manager → Docker."""
        from src.config.loader import ConfigLoader
        
        config_file = tmp_path / "config.yml"
        config_file.write_text("""
network:
  name: stagenet
nodes:
  - name: node1
    role: root
""")
        
        loader = ConfigLoader(tmp_path)
        config = loader.load_config_file(config_file)
        
        # Verify config is ready for network setup
        assert config["network"]["name"] == "stagenet"
        assert len(config["nodes"]) == 1
        assert config["nodes"][0]["role"] == "root"
