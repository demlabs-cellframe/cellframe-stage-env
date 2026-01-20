"""Compact integration tests for stage-env modules."""

import pytest
from pathlib import Path
import tempfile
import shutil


class TestMinimalIntegrations:
    """Basic integration tests ensuring modules work together."""
    
    def test_imports_integration(self):
        """Test that all main modules can be imported together."""
        # This test verifies no circular dependencies or import conflicts
        from src.config import loader
        from src.docker_ctl import container, compose
        from src.scenarios import executor, parser
        from src.build import builder
        from src.snapshots import manager
        from src.monitoring import datum
        
        assert loader is not None
        assert container is not None
        assert compose is not None
        assert executor is not None
        assert parser is not None
        assert builder is not None
        assert manager is not None
        assert datum is not None
    
    def test_config_to_docker_integration(self, tmp_path):
        """Test config can be loaded and passed to docker modules."""
        from src.config.loader import ConfigLoader
        
        # Create minimal config
        config_file = tmp_path / "config.yml"
        config_file.write_text("""
network:
  name: stagenet
""")
        
        loader = ConfigLoader(tmp_path)
        config = loader.load_yaml(config_file)
        
        # Config should be usable by other modules
        assert config is not None
        assert "network" in config
    
    def test_scenario_parser_basic_integration(self, tmp_path):
        """Test scenario parser can parse a file."""
        from src.scenarios.parser import ScenarioParser
        import yaml
        
        # Create scenarios directory
        scenarios_dir = tmp_path / "scenarios"
        scenarios_dir.mkdir()
        
        scenario_file = scenarios_dir / "test.yml"
        # Correct structure according to TestScenario schema
        scenario_file.write_text(yaml.dump({
            "name": "test",
            "description": "test scenario",
            "network": {"preset": "minimal"},
            "test": {
                "steps": [
                    {"cli": "version", "node": "node1", "name": "step1"}
                ]
            }
        }))
        
        parser = ScenarioParser(scenarios_root=scenarios_dir)
        result = parser.load_scenario("test.yml")
        
        assert result is not None
        assert result.name == "test"
    
    def test_utils_modules_integration(self):
        """Test utils modules work together."""
        from src.utils import logger, cli, pid_manager
        
        assert logger is not None
        assert cli is not None
        assert pid_manager is not None
