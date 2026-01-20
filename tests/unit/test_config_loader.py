"""Unit tests for src/config/loader.py - minimal stubs."""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

class TestConfigLoader:
    """Stub tests for ConfigLoader."""
    
    def test_import_configloader(self):
        """Test importing ConfigLoader."""
        from src.config.loader import ConfigLoader
        assert ConfigLoader is not None
    
    def test_configloader_instantiation(self, tmp_path):
        """Test creating ConfigLoader instance."""
        from src.config.loader import ConfigLoader
        config_file = tmp_path / "test.cfg"
        config_file.write_text("[general]\n")
        loader = ConfigLoader(config_file)
        assert loader is not None
