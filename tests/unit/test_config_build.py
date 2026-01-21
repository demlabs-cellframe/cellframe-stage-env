"""Unit tests for build configuration loading."""

import pytest
from pathlib import Path
import tempfile
import shutil

from src.config.loader import ConfigLoader


class TestBuildConfigLoader:
    """Test ConfigLoader.get_build_config() method."""
    
    @pytest.fixture
    def temp_base_path(self):
        """Create temporary base path with config directory."""
        temp_dir = Path(tempfile.mkdtemp())
        config_dir = temp_dir / "config"
        config_dir.mkdir()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    def test_get_build_config_defaults(self, temp_base_path):
        """Test get_build_config with no config file (uses defaults)."""
        loader = ConfigLoader(temp_base_path)
        build_config = loader.get_build_config()
        
        assert build_config['build_type'] == 'debug'
        assert build_config['cellframe_version'] == 'latest'
        assert build_config['auto_build'] is False
    
    def test_get_build_config_with_config_file(self, temp_base_path):
        """Test get_build_config with valid config file."""
        config_file = temp_base_path / "config" / "stage-env.cfg"
        config_file.write_text("""[build]
build_type = release
cellframe_version = 5.6
auto_build = true
""")
        
        loader = ConfigLoader(temp_base_path)
        build_config = loader.get_build_config()
        
        assert build_config['build_type'] == 'release'
        assert build_config['cellframe_version'] == '5.6'
        assert build_config['auto_build'] is True
    
    def test_get_build_config_auto_build_false(self, temp_base_path):
        """Test get_build_config with auto_build explicitly disabled."""
        config_file = temp_base_path / "config" / "stage-env.cfg"
        config_file.write_text("""[build]
auto_build = false
""")
        
        loader = ConfigLoader(temp_base_path)
        build_config = loader.get_build_config()
        
        assert build_config['auto_build'] is False
    
    def test_get_build_config_invalid_auto_build(self, temp_base_path):
        """Test get_build_config with invalid auto_build value."""
        config_file = temp_base_path / "config" / "stage-env.cfg"
        config_file.write_text("""[build]
auto_build = invalid
""")
        
        loader = ConfigLoader(temp_base_path)
        build_config = loader.get_build_config()
        
        # Should fallback to False on invalid value
        assert build_config['auto_build'] is False
    
    def test_get_build_config_partial_settings(self, temp_base_path):
        """Test get_build_config with only some settings specified."""
        config_file = temp_base_path / "config" / "stage-env.cfg"
        config_file.write_text("""[build]
build_type = release
""")
        
        loader = ConfigLoader(temp_base_path)
        build_config = loader.get_build_config()
        
        assert build_config['build_type'] == 'release'
        # Others should use defaults
        assert build_config['cellframe_version'] == 'latest'
        assert build_config['auto_build'] is False
    
    def test_get_build_config_no_build_section(self, temp_base_path):
        """Test get_build_config with config file but no [build] section."""
        config_file = temp_base_path / "config" / "stage-env.cfg"
        config_file.write_text("""[network]
name = testnet
""")
        
        loader = ConfigLoader(temp_base_path)
        build_config = loader.get_build_config()
        
        # Should return all defaults
        assert build_config['build_type'] == 'debug'
        assert build_config['cellframe_version'] == 'latest'
        assert build_config['auto_build'] is False


class TestBuildConfigIntegration:
    """Integration tests for build config with other components."""
    
    @pytest.fixture
    def temp_base_path(self):
        """Create temporary base path."""
        temp_dir = Path(tempfile.mkdtemp())
        (temp_dir / "config").mkdir()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    def test_build_config_used_by_network_manager(self, temp_base_path):
        """Test that build config can be loaded for NetworkManager."""
        config_file = temp_base_path / "config" / "stage-env.cfg"
        config_file.write_text("""[build]
auto_build = true
build_type = debug

[network]
name = stagenet
""")
        
        loader = ConfigLoader(temp_base_path)
        build_config = loader.get_build_config()
        
        # Verify config is ready for NetworkManager consumption
        assert isinstance(build_config, dict)
        assert 'auto_build' in build_config
        assert 'build_type' in build_config
        assert build_config['auto_build'] is True
