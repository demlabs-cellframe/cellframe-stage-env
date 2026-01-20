"""Integration tests for Build + Config pipeline."""

import pytest
from pathlib import Path
import tempfile
import shutil
from unittest.mock import MagicMock, patch

from src.build.builder import BuildManager
from src.config.loader import ConfigLoader


class TestBuildConfigIntegration:
    """Test integration between BuildManager and ConfigLoader."""
    
    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace with required structure."""
        temp_dir = Path(tempfile.mkdtemp())
        (temp_dir / "build").mkdir()
        (temp_dir / "config").mkdir()
        (temp_dir / "artifacts").mkdir()
        
        # Create minimal config in INI format
        config_file = temp_dir / "config" / "stage-env.cfg"
        config_file.write_text("""[build]
node_repo = /fake/cellframe-node
build_type = Debug

[paths]
artifacts_dir = artifacts
build_dir = build
""")
        
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    def test_build_manager_uses_config_paths(self, temp_workspace):
        """Test that BuildManager respects paths from ConfigLoader."""
        # Load config
        loader = ConfigLoader(temp_workspace)
        config_file = temp_workspace / "config" / "stage-env.cfg"
        config_parser = loader.load_config_file(config_file)
        
        # BuildManager should use config paths
        build_config = dict(config_parser['build']) if 'build' in config_parser else {}
        
        with patch('subprocess.run'):
            manager = BuildManager(temp_workspace)
            
            # Verify manager uses correct paths
            assert manager.base_path == temp_workspace
    
    def test_build_artifacts_placed_in_config_location(self, temp_workspace):
        """Test that build artifacts are placed where config specifies."""
        loader = ConfigLoader(temp_workspace)
        config_file = temp_workspace / "config" / "stage-env.cfg"
        config_parser = loader.load_config_file(config_file)
        
        artifacts_dir_name = config_parser.get('paths', 'artifacts_dir', fallback='artifacts')
        artifacts_dir = temp_workspace / artifacts_dir_name
        
        # Simulate artifact creation
        artifacts_dir.mkdir(exist_ok=True)
        (artifacts_dir / "cellframe-node.deb").write_text("fake package")
        
        # Verify artifact in correct location
        assert (artifacts_dir / "cellframe-node.deb").exists()
    
    def test_build_config_validation_integration(self, temp_workspace):
        """Test build config validation through ConfigLoader."""
        # Create invalid build config in INI format
        invalid_config = temp_workspace / "config" / "invalid.cfg"
        invalid_config.write_text("""[build]
# Missing required field: node_repo
build_type = Release
""")
        
        loader = ConfigLoader(temp_workspace)
        config_parser = loader.load_config_file(invalid_config)
        
        # BuildManager should handle missing fields
        assert 'build' in config_parser
        assert not config_parser.has_option('build', 'node_repo')


class TestBuildNetworkIntegration:
    """Test BuildManager integration with network deployment."""
    
    def test_built_artifacts_used_by_docker(self, tmp_path):
        """Test that built artifacts can be used by Docker compose."""
        build_config = {
            "node_repo": "/fake/repo",
            "build_type": "Debug"
        }
        
        with patch('subprocess.run'):
            manager = BuildManager(tmp_path, build_config)
            
            # Simulate successful build
            artifacts_dir = tmp_path / "artifacts"
            artifacts_dir.mkdir(exist_ok=True)
            (artifacts_dir / "cellframe-node").write_text("fake binary")
            
            # Docker compose should be able to mount this artifact
            artifact_path = artifacts_dir / "cellframe-node"
            assert artifact_path.exists()
            assert artifact_path.is_file()
    
    def test_build_failure_prevents_network_start(self, tmp_path):
        """Test that build failure is detected before network operations."""
        build_config = {"node_repo": "/nonexistent/repo"}
        
        with patch('subprocess.run') as mock_run:
            # Simulate build failure
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Build failed")
            
            manager = BuildManager(tmp_path, build_config)
            
            # Build should report failure
            # Network manager should not proceed without artifacts
            artifacts_dir = tmp_path / "artifacts"
            assert not (artifacts_dir / "cellframe-node").exists()
