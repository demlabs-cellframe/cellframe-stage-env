"""Unit tests for src/config/ modules."""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestConfigLoader:
    """Test ConfigLoader."""
    
    def test_config_loader_import(self):
        from src.config.loader import ConfigLoader
        assert ConfigLoader is not None
    
    def test_config_loader_init(self, tmp_path):
        from src.config.loader import ConfigLoader
        loader = ConfigLoader(tmp_path)
        assert loader.base_path == tmp_path


class TestConfigGenerator:
    """Test ConfigGenerator."""
    
    def test_config_generator_import(self):
        from src.config.generator import ConfigGenerator
        assert ConfigGenerator is not None


class TestConfigManager:
    """Test ConfigManager."""
    
    def test_config_manager_import(self):
        from src.config import manager
        assert manager is not None


class TestConfigIntegration:
    """Integration tests."""
    
    def test_config_modules_importable(self):
        from src.config import loader, generator, manager
        assert all([loader, generator, manager])
