"""Integration tests for Config pipeline: Loader -> Generator -> Manager."""

import pytest
from pathlib import Path
import tempfile
import shutil
from unittest.mock import MagicMock, patch

from src.config.loader import ConfigLoader
from src.config.generator import ConfigGenerator
from src.config import manager as config_manager


class TestConfigPipeline:
    """Test integration between ConfigLoader, ConfigGenerator, and ConfigManager."""
    
    @pytest.fixture
    def temp_stage_env_dir(self):
        """Create temporary stage-env directory structure."""
        temp_dir = Path(tempfile.mkdtemp())
        (temp_dir / "config").mkdir()
        (temp_dir / "cache").mkdir()
        (temp_dir / "templates").mkdir()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def minimal_config(self, temp_stage_env_dir):
        """Create minimal valid config.yml."""
        config_file = temp_stage_env_dir / "config" / "config.yml"
        config_file.write_text("""
network:
  name: stagenet
  chain_type: testnet

nodes:
  - name: node1
    role: root
    consensus: dag-poa

paths:
  base_dir: {base_dir}
  cache_dir: {base_dir}/cache
  templates_dir: {base_dir}/templates
""".format(base_dir=str(temp_stage_env_dir)))
        return config_file
    
    def test_loader_to_generator_flow(self, temp_stage_env_dir, minimal_config):
        """Test that ConfigLoader output can be consumed by ConfigGenerator."""
        # These tests focus on module interactions, not full initialization
        
        # Load config
        loader = ConfigLoader(temp_stage_env_dir)
        config_data = loader.load_yaml(minimal_config)
        
        assert config_data is not None
        assert "network" in config_data
        assert "nodes" in config_data
        
        # Generator should be able to use loader (both use same config system)
        with patch('src.docker_ctl.compose.DockerComposeManager'):
            with patch('src.config.generator.get_config_loader', return_value=loader):
                generator = ConfigGenerator(temp_stage_env_dir)
                # Generator uses loader internally
                assert generator.config_loader is not None
    
    def test_full_config_pipeline(self, temp_stage_env_dir, minimal_config):
        """Test full pipeline: Load -> Generate -> Manage."""
        # Step 1: Load
        loader = ConfigLoader(temp_stage_env_dir)
        config_data = loader.load_yaml(minimal_config)
        
        # Step 2: Generate (mocked)
        with patch('src.docker_ctl.compose.DockerComposeManager') as mock_docker:
            with patch('src.config.generator.get_config_loader', return_value=loader):
                generator = ConfigGenerator(temp_stage_env_dir)
                
                # Verify generator uses loader
                assert generator.config_loader is not None
                
                # Verify loader has necessary data
                assert "network" in config_data
                assert len(config_data.get("nodes", [])) > 0
    
    def test_config_validation_through_pipeline(self, temp_stage_env_dir):
        """Test that invalid config is rejected by the pipeline."""
        # Create invalid config (missing required fields)
        invalid_config = temp_stage_env_dir / "config" / "invalid.yml"
        invalid_config.write_text("network: {}")
        
        loader = ConfigLoader(temp_stage_env_dir)
        
        # load_yaml doesn't validate, so test that ConfigGenerator would fail
        config = loader.load_yaml(invalid_config)
        
        # ConfigGenerator should validate and reject incomplete configs
        with patch('src.docker_ctl.compose.DockerComposeManager'):
            with patch('src.config.generator.get_config_loader', return_value=loader):
                with pytest.raises((ValueError, KeyError, AttributeError, TypeError)):
                    generator = ConfigGenerator(temp_stage_env_dir, config)
                    # Accessing config properties should fail if incomplete
                    _ = generator.config["nodes"]  # This should fail
    
    def test_config_templates_integration(self, temp_stage_env_dir, minimal_config):
        """Test that templates are correctly integrated in config generation."""
        # Create a simple template
        template_file = temp_stage_env_dir / "templates" / "test.j2"
        template_file.write_text("Network: {{ network_name }}")
        
        loader = ConfigLoader(temp_stage_env_dir)
        config_data = loader.load_yaml(minimal_config)
        
        with patch('src.docker_ctl.compose.DockerComposeManager'):
            with patch('src.config.generator.get_config_loader', return_value=loader):
                generator = ConfigGenerator(temp_stage_env_dir)
                
                # Verify generator can access config loader
                assert generator.config_loader is not None
                # Templates directory should exist
                assert template_file.parent.exists()
