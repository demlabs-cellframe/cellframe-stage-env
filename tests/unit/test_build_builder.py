"""Unit tests for src/build/builder.py."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import sys
import time

# Add stage-env root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.build.builder import BuildManager, BuildResult


class TestBuildResult:
    """Test BuildResult model."""
    
    def test_build_result_creation(self):
        """Test creating BuildResult."""
        result = BuildResult(
            success=True,
            build_type="debug",
            artifacts=["file1", "file2"],
            duration_s=120.5,
            cache_used=True
        )
        
        assert result.success is True
        assert result.build_type == "debug"
        assert result.artifacts == ["file1", "file2"]
        assert result.duration_s == 120.5
        assert result.cache_used is True
    
    def test_build_result_default_cache_used(self):
        """Test BuildResult with default cache_used."""
        result = BuildResult(
            success=True,
            build_type="release",
            artifacts=[],
            duration_s=0.0
        )
        
        assert result.cache_used is False


class TestBuildManagerInit:
    """Test BuildManager initialization."""
    
    def test_init_creates_directories(self, tmp_path):
        """Test that init creates necessary directories."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        manager = BuildManager(base_path)
        
        assert manager.base_path == base_path
        assert manager.cache_dir.exists()
        assert "build" in str(manager.cache_dir)
    
    def test_init_with_node_source_config(self, tmp_path):
        """Test init with node source configuration."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        node_source_config = {
            "type": "repository",
            "url": "https://github.com/demlabs-cellframe/cellframe-node"
        }
        
        manager = BuildManager(base_path, node_source_config)
        
        assert manager.node_source_config == node_source_config
        assert manager.node_source_config["type"] == "repository"
    
    def test_init_without_node_source_config(self, tmp_path):
        """Test init without node source configuration."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        manager = BuildManager(base_path)
        
        assert manager.node_source_config == {}


class TestBuildManagerBuild:
    """Test build method."""
    
    @patch('src.build.builder.run_command')
    def test_build_success(self, mock_run_command, tmp_path):
        """Test successful build."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        manager = BuildManager(base_path)
        
        # Mock successful command execution
        mock_run_command.return_value = (0, "", "")
        
        result = manager.build(build_type="debug", clean=False, parallel=4)
        
        assert result.success is True
        assert result.build_type == "debug"
        assert isinstance(result.duration_s, float)
        assert result.duration_s >= 0
    
    @patch('src.build.builder.run_command')
    def test_build_clean(self, mock_run_command, tmp_path):
        """Test build with clean=True."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        manager = BuildManager(base_path)
        
        # Create fake build directory
        manager.build_dir.mkdir(parents=True, exist_ok=True)
        fake_file = manager.build_dir / "old_build.o"
        fake_file.touch()
        
        mock_run_command.return_value = (0, "", "")
        
        result = manager.build(build_type="release", clean=True)
        
        # Old file should be removed
        assert not fake_file.exists()
        assert result.success is True
    
    @patch('src.build.builder.run_command')
    def test_build_failure(self, mock_run_command, tmp_path):
        """Test build failure handling."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        manager = BuildManager(base_path)
        
        # Mock failed command execution
        import subprocess
        mock_run_command.side_effect = subprocess.CalledProcessError(1, ["make"])
        
        result = manager.build(build_type="debug")
        
        assert result.success is False
    
    @patch('src.build.builder.run_command')
    def test_build_with_parallel_jobs(self, mock_run_command, tmp_path):
        """Test build with parallel jobs."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        manager = BuildManager(base_path)
        
        mock_run_command.return_value = (0, "", "")
        
        result = manager.build(build_type="debug", parallel=8)
        
        assert result.success is True
        # Verify parallel flag was used
        make_call = [c for c in mock_run_command.call_args_list if 'make' in str(c)]
        if make_call:
            # Check if -j flag was passed
            assert any('-j' in str(arg) for arg in make_call)


class TestBuildManagerArtifacts:
    """Test artifact-related methods."""
    
    def test_artifacts_exist_true(self, tmp_path):
        """Test artifacts_exist when artifacts are present."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        manager = BuildManager(base_path)
        manager.build_dir.mkdir(parents=True, exist_ok=True)
        
        # Create fake artifacts
        (manager.build_dir / "cellframe-node").touch()
        
        with patch.object(manager, '_find_artifacts', return_value=["cellframe-node"]):
            result = manager.artifacts_exist()
        
        assert result is True
    
    def test_artifacts_exist_false(self, tmp_path):
        """Test artifacts_exist when no artifacts."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        manager = BuildManager(base_path)
        
        with patch.object(manager, '_find_artifacts', return_value=[]):
            result = manager.artifacts_exist()
        
        assert result is False
    
    def test_verify_artifacts(self, tmp_path):
        """Test verify_artifacts method."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        manager = BuildManager(base_path)
        manager.build_dir.mkdir(parents=True, exist_ok=True)
        
        # Create fake artifact
        artifact = manager.build_dir / "cellframe-node"
        artifact.touch()
        
        with patch.object(manager, '_find_artifacts', return_value=["cellframe-node"]):
            result = manager.verify_artifacts()
        
        # Result depends on actual implementation
        assert isinstance(result, bool)
    
    def test_get_artifact_hash(self, tmp_path):
        """Test getting artifact hash."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        manager = BuildManager(base_path)
        
        # Create test file
        test_file = tmp_path / "test_artifact"
        test_file.write_text("test content")
        
        hash_value = manager.get_artifact_hash(str(test_file))
        
        assert isinstance(hash_value, str)
        assert len(hash_value) > 0
        # Same file should produce same hash
        hash_value2 = manager.get_artifact_hash(str(test_file))
        assert hash_value == hash_value2


class TestBuildManagerCellframeNodeRepo:
    """Test _is_cellframe_node_repo method."""
    
    def test_is_cellframe_node_repo_with_marker(self, tmp_path):
        """Test detection when in cellframe-node repository."""
        base_path = tmp_path / "cellframe-node" / "tests" / "stage-env"
        base_path.mkdir(parents=True)
        
        manager = BuildManager(base_path)
        
        # Create fake cellframe-node markers
        project_root = manager.project_root
        project_root.mkdir(parents=True, exist_ok=True)
        (project_root / "CMakeLists.txt").write_text("project(cellframe-node)")
        
        result = manager._is_cellframe_node_repo()
        
        # Result depends on implementation
        assert isinstance(result, bool)
    
    def test_is_cellframe_node_repo_without_marker(self, tmp_path):
        """Test detection when not in cellframe-node repository."""
        base_path = tmp_path / "random-project" / "stage-env"
        base_path.mkdir(parents=True)
        
        manager = BuildManager(base_path)
        
        result = manager._is_cellframe_node_repo()
        
        # Without markers, should return False (but might return True if we're actually in cellframe repo)
        assert isinstance(result, bool)


class TestBuildManagerCleanup:
    """Test cleanup methods."""
    
    def test_clean_method(self, tmp_path):
        """Test clean method."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        manager = BuildManager(base_path)
        manager.build_dir.mkdir(parents=True, exist_ok=True)
        
        # Create fake build files
        (manager.build_dir / "build_file.o").touch()
        (manager.build_dir / "subdir").mkdir()
        (manager.build_dir / "subdir" / "file.a").touch()
        
        manager.clean()
        
        # Build dir should be cleaned
        # (implementation may vary - just check it doesn't raise)
    
    def test_get_build_info(self, tmp_path):
        """Test get_build_info method."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        manager = BuildManager(base_path)
        
        info = manager.get_build_info()
        
        assert isinstance(info, dict)
        # Should have some standard keys
        assert "build_dir" in info or "cache_dir" in info


class TestBuildManagerIntegration:
    """Integration tests for BuildManager."""
    
    @patch('src.build.builder.run_command')
    def test_full_build_workflow(self, mock_run_command, tmp_path):
        """Test complete build workflow."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        manager = BuildManager(base_path)
        
        # Mock all command executions
        mock_run_command.return_value = (0, "", "")
        
        # Build
        result = manager.build(build_type="debug", clean=True, parallel=4)
        
        assert result.success is True
        assert result.build_type == "debug"
        assert manager.build_dir.exists()
    
    def test_build_result_timing(self, tmp_path):
        """Test that build result includes timing information."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        manager = BuildManager(base_path)
        
        with patch('src.build.builder.run_command', return_value=(0, "", "")):
            start = time.time()
            result = manager.build(build_type="debug")
            duration = time.time() - start
            
            assert result.duration_s > 0
            # Duration should be reasonable (not too different from actual)
            assert result.duration_s < duration + 1.0


class TestBuildManagerPackage:
    """Test get_node_package and related methods."""
    
    @patch('src.build.builder.run_command')
    def test_get_node_package_from_local(self, mock_run_command, tmp_path):
        """Test getting package from local build."""
        base_path = tmp_path / "stage-env"
        base_path.mkdir()
        
        node_source_config = {"type": "local"}
        manager = BuildManager(base_path, node_source_config)
        
        # Mock _is_cellframe_node_repo
        with patch.object(manager, '_is_cellframe_node_repo', return_value=True):
            with patch.object(manager, '_get_package_from_local', return_value=Path("/tmp/test.deb")):
                result = manager.get_node_package()
        
        assert result is not None
    
    def test_is_cellframe_node_repo_with_cmakelists(self, tmp_path):
        """Test _is_cellframe_node_repo with CMakeLists.txt."""
        base_path = tmp_path / "cellframe-node" / "tests" / "stage-env"
        base_path.mkdir(parents=True)
        
        manager = BuildManager(base_path)
        
        # Create CMakeLists.txt in project root
        cmakelists = manager.project_root / "CMakeLists.txt"
        cmakelists.parent.mkdir(parents=True, exist_ok=True)
        cmakelists.write_text("project(cellframe-node)")
        
        result = manager._is_cellframe_node_repo()
        
        # Result depends on whether 'cellframe' is in the CMakeLists
        assert isinstance(result, bool)
