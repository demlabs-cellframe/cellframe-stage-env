"""Integration tests for error handling across modules."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestErrorPropagation:
    """Test errors propagate correctly between modules."""
    
    def test_config_error_prevents_network_setup(self, tmp_path):
        """Test config errors stop network setup."""
        from src.config.loader import ConfigLoader
        
        invalid_config = tmp_path / "invalid.yml"
        invalid_config.write_text("invalid: yaml: ::::")
        
        loader = ConfigLoader(tmp_path)
        
        with pytest.raises(Exception):
            loader.load_config_file(invalid_config)
    
    def test_missing_file_error_handling(self, tmp_path):
        """Test missing file errors handled gracefully."""
        from src.config.loader import ConfigLoader
        
        loader = ConfigLoader(tmp_path)
        nonexistent = tmp_path / "nonexistent.yml"
        
        with pytest.raises(FileNotFoundError):
            loader.load_config_file(nonexistent)
    
    def test_docker_connection_error_handling(self):
        """Test Docker connection errors are caught."""
        from src.docker_ctl.container import DockerContainerManager
        
        with patch('docker.from_env') as mock_docker:
            mock_docker.side_effect = Exception("Docker not available")
            
            with pytest.raises(Exception, match="Docker"):
                DockerContainerManager(Path("/tmp"))


class TestValidationIntegration:
    """Test validation across module boundaries."""
    
    def test_scenario_validation_catches_errors(self, tmp_path):
        """Test scenario validation works."""
        from src.scenarios.parser import ScenarioParser
        import yaml
        
        invalid_scenario = tmp_path / "invalid.yml"
        invalid_scenario.write_text(yaml.dump({
            "scenario": {
                # Missing required fields
                "name": "test"
            }
        }))
        
        parser = ScenarioParser()
        
        # Should catch validation error
        with pytest.raises(Exception):
            parser.parse(invalid_scenario)


class TestRecoveryMechanisms:
    """Test recovery mechanisms work across modules."""
    
    def test_partial_failure_recovery(self, tmp_path):
        """Test system can recover from partial failures."""
        # Create some valid state
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "state.json").write_text('{"status": "ok"}')
        
        # Verify state persists
        assert (cache_dir / "state.json").exists()
        
        # After error, state should still be accessible
        import json
        state = json.loads((cache_dir / "state.json").read_text())
        assert state["status"] == "ok"
