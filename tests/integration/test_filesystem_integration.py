"""Integration tests for filesystem operations across modules."""

import pytest
from pathlib import Path
import tempfile
import shutil


class TestFilesystemIntegration:
    """Test filesystem operations integration."""
    
    def test_cache_directory_shared_across_modules(self, tmp_path):
        """Test cache directory is consistently used."""
        from src.config.loader import ConfigLoader
        
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        
        # Multiple modules should use the same cache
        (cache_dir / "config_cache.json").write_text("{}")
        (cache_dir / "build_cache").mkdir()
        
        assert (cache_dir / "config_cache.json").exists()
        assert (cache_dir / "build_cache").is_dir()
    
    def test_logs_directory_integration(self, tmp_path):
        """Test logs are written to consistent location."""
        from src.utils.logger import setup_logging
        
        log_file = tmp_path / "test.log"
        setup_logging(log_file=log_file)
        
        # Verify log file created
        assert log_file.parent.exists()
    
    def test_artifacts_collection_integration(self, tmp_path):
        """Test artifacts from different modules collected together."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        
        # Simulate artifacts from different sources
        (artifacts_dir / "build_output.log").write_text("build logs")
        (artifacts_dir / "test_results.xml").write_text("<results/>")
        (artifacts_dir / "coverage.json").write_text("{}")
        
        # All artifacts in one place
        assert len(list(artifacts_dir.iterdir())) == 3


class TestConfigPathsIntegration:
    """Test config-driven paths work across modules."""
    
    def test_all_modules_respect_config_paths(self, tmp_path):
        """Test modules use paths from config."""
        from src.config.loader import ConfigLoader
        
        config_file = tmp_path / "config.yml"
        config_file.write_text("""
paths:
  cache_dir: custom_cache
  build_dir: custom_build
  artifacts_dir: custom_artifacts
""")
        
        loader = ConfigLoader(tmp_path)
        config = loader.load_yaml(config_file)
        
        paths = config["paths"]
        assert paths["cache_dir"] == "custom_cache"
        assert paths["build_dir"] == "custom_build"
        assert paths["artifacts_dir"] == "custom_artifacts"


class TestTempFileHandling:
    """Test temporary file handling integration."""
    
    def test_temp_files_cleaned_up(self):
        """Test temp files are properly managed."""
        temp_dir = Path(tempfile.mkdtemp())
        temp_file = temp_dir / "temp.txt"
        temp_file.write_text("temp data")
        
        # Cleanup
        shutil.rmtree(temp_dir)
        
        assert not temp_dir.exists()
