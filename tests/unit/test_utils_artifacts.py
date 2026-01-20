"""Unit tests for src/utils/artifacts.py."""

import pytest
import json
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, mock_open
import sys

# Add stage-env root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.artifacts import ArtifactsManager


class TestArtifactsManagerInit:
    """Test ArtifactsManager initialization."""
    
    def test_init_creates_artifacts_dir(self, tmp_path):
        """Test that init creates artifacts directory."""
        config = {
            'artifacts_dir': 'artifacts',
            'collect_node_logs': True,
            'collect_health_logs': True,
            'collect_crash_dumps': True,
            'retain_days': 30,
        }
        
        manager = ArtifactsManager(tmp_path, config)
        
        assert manager.artifacts_root.exists()
        assert manager.should_collect_node_logs is True
        assert manager.should_collect_health_logs is True
        assert manager.should_collect_crash_dumps is True
        assert manager.retain_days == 30
    
    def test_init_with_custom_config(self, tmp_path):
        """Test init with custom configuration."""
        config = {
            'artifacts_dir': 'custom_artifacts',
            'collect_node_logs': False,
            'retain_days': 7,
        }
        
        manager = ArtifactsManager(tmp_path, config)
        
        assert manager.should_collect_node_logs is False
        assert manager.retain_days == 7
        assert 'custom_artifacts' in str(manager.artifacts_root)
    
    def test_init_with_defaults(self, tmp_path):
        """Test init with default values."""
        config = {}
        
        manager = ArtifactsManager(tmp_path, config)
        
        # Should use defaults
        assert manager.should_collect_node_logs is True
        assert manager.should_collect_health_logs is True
        assert manager.should_collect_crash_dumps is True
        assert manager.retain_days == 30


class TestCreateRunDirectory:
    """Test create_run_directory method."""
    
    def test_create_run_directory_default(self, tmp_path):
        """Test creating run directory with default run_id."""
        config = {'artifacts_dir': 'artifacts'}
        manager = ArtifactsManager(tmp_path, config)
        
        run_dir = manager.create_run_directory()
        
        assert run_dir.exists()
        assert run_dir.name.startswith("run_")
        
        # Check subdirectories exist
        assert (run_dir / "stage-env-logs").exists()
        assert (run_dir / "node-logs").exists()
        assert (run_dir / "core-dumps").exists()
        assert (run_dir / "stack-traces").exists()
        assert (run_dir / "health-logs").exists()
    
    def test_create_run_directory_with_run_id(self, tmp_path):
        """Test creating run directory with custom run_id."""
        config = {'artifacts_dir': 'artifacts'}
        manager = ArtifactsManager(tmp_path, config)
        
        run_dir = manager.create_run_directory(run_id="test_run_123")
        
        assert run_dir.name == "run_test_run_123"
    
    def test_create_run_directory_with_test_type(self, tmp_path):
        """Test creating run directory with test_type."""
        config = {'artifacts_dir': 'artifacts'}
        manager = ArtifactsManager(tmp_path, config)
        
        run_dir = manager.create_run_directory(run_id="test", test_type="e2e")
        
        assert (run_dir / "stage-env-logs").exists()
        assert "e2e" in str(run_dir)


class TestCollectStageEnvLog:
    """Test collect_stage_env_log method."""
    
    def test_collect_stage_env_log_success(self, tmp_path):
        """Test collecting stage-env log successfully."""
        config = {'artifacts_dir': 'artifacts'}
        manager = ArtifactsManager(tmp_path, config)
        run_dir = manager.create_run_directory(run_id="test")
        
        # Create a fake log file
        log_file = tmp_path / "stage-env.log"
        log_file.write_text("test log content")
        
        manager.collect_stage_env_log(run_dir, log_file)
        
        # Verify log was copied
        dest = run_dir / "stage-env-logs" / log_file.name
        assert dest.exists()
        assert dest.read_text() == "test log content"
    
    def test_collect_stage_env_log_missing_file(self, tmp_path):
        """Test collecting non-existent log file."""
        config = {'artifacts_dir': 'artifacts'}
        manager = ArtifactsManager(tmp_path, config)
        run_dir = manager.create_run_directory(run_id="test")
        
        log_file = tmp_path / "nonexistent.log"
        
        # Should not raise
        manager.collect_stage_env_log(run_dir, log_file)


class TestCollectNodeLogs:
    """Test collect_node_logs method."""
    
    def test_collect_node_logs_enabled(self, tmp_path):
        """Test collecting node logs when enabled."""
        config = {'artifacts_dir': 'artifacts', 'collect_node_logs': True}
        manager = ArtifactsManager(tmp_path, config)
        run_dir = manager.create_run_directory(run_id="test")
        
        # Mock Docker client
        mock_container = MagicMock()
        mock_container.logs.return_value = b"node log content"
        
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        
        manager.collect_node_logs(run_dir, mock_client, ["node1", "node2"])
        
        # Should have called containers.get for each node
        assert mock_client.containers.get.call_count == 2
        
        # Verify logs were written
        node1_log = run_dir / "node-logs" / "node1.log"
        assert node1_log.exists()
        assert "node log content" in node1_log.read_text()
    
    def test_collect_node_logs_disabled(self, tmp_path):
        """Test that node logs are not collected when disabled."""
        config = {'artifacts_dir': 'artifacts', 'collect_node_logs': False}
        manager = ArtifactsManager(tmp_path, config)
        run_dir = manager.create_run_directory(run_id="test")
        
        mock_client = MagicMock()
        
        manager.collect_node_logs(run_dir, mock_client, ["node1"])
        
        # Should not call Docker client
        mock_client.containers.get.assert_not_called()
    
    def test_collect_node_logs_handles_errors(self, tmp_path):
        """Test that errors in node log collection are handled."""
        config = {'artifacts_dir': 'artifacts', 'collect_node_logs': True}
        manager = ArtifactsManager(tmp_path, config)
        run_dir = manager.create_run_directory(run_id="test")
        
        mock_client = MagicMock()
        mock_client.containers.get.side_effect = Exception("Container not found")
        
        # Should not raise
        manager.collect_node_logs(run_dir, mock_client, ["node1"])


class TestCollectCoreDumps:
    """Test collect_core_dumps method."""
    
    def test_collect_core_dumps_disabled(self, tmp_path):
        """Test that core dumps are not collected when disabled."""
        config = {'artifacts_dir': 'artifacts', 'collect_crash_dumps': False}
        manager = ArtifactsManager(tmp_path, config)
        run_dir = manager.create_run_directory(run_id="test")
        
        mock_client = MagicMock()
        
        manager.collect_core_dumps(run_dir, mock_client, ["node1"])
        
        # Should not call Docker client
        mock_client.containers.get.assert_not_called()
    
    def test_collect_core_dumps_no_dumps_found(self, tmp_path):
        """Test collecting core dumps when none exist."""
        config = {'artifacts_dir': 'artifacts', 'collect_crash_dumps': True}
        manager = ArtifactsManager(tmp_path, config)
        run_dir = manager.create_run_directory(run_id="test")
        
        mock_container = MagicMock()
        # exec_run returns no files
        mock_container.exec_run.return_value = MagicMock(exit_code=0, output=b"")
        
        mock_client = MagicMock()
        mock_client.containers.get.return_value = mock_container
        
        # Should not raise
        manager.collect_core_dumps(run_dir, mock_client, ["node1"])


class TestCleanupOldArtifacts:
    """Test cleanup_old_artifacts method."""
    
    def test_cleanup_old_artifacts(self, tmp_path):
        """Test cleaning up old artifacts."""
        config = {'artifacts_dir': 'artifacts', 'retain_days': 7}
        manager = ArtifactsManager(tmp_path, config)
        
        # Create old run directory
        old_run_dir = manager.artifacts_root / "run_old"
        old_run_dir.mkdir()
        
        # Set modification time to 30 days ago
        old_time = (datetime.now() - timedelta(days=30)).timestamp()
        import os
        os.utime(old_run_dir, (old_time, old_time))
        
        # Create recent run directory
        recent_run_dir = manager.artifacts_root / "run_recent"
        recent_run_dir.mkdir()
        
        manager.cleanup_old_artifacts()
        
        # Old directory should be removed
        assert not old_run_dir.exists()
        # Recent directory should remain
        assert recent_run_dir.exists()
    
    def test_cleanup_no_old_artifacts(self, tmp_path):
        """Test cleanup when no old artifacts exist."""
        config = {'artifacts_dir': 'artifacts', 'retain_days': 7}
        manager = ArtifactsManager(tmp_path, config)
        
        # Create recent run directory
        recent_run_dir = manager.artifacts_root / "run_recent"
        recent_run_dir.mkdir()
        
        # Should not raise
        manager.cleanup_old_artifacts()
        
        # Recent directory should still exist
        assert recent_run_dir.exists()


class TestCreateRunSummary:
    """Test create_run_summary method."""
    
    def test_create_run_summary(self, tmp_path):
        """Test creating run summary."""
        config = {'artifacts_dir': 'artifacts'}
        manager = ArtifactsManager(tmp_path, config)
        run_dir = manager.create_run_directory(run_id="test")
        
        summary_data = {
            "test_count": 10,
            "passed": 8,
            "failed": 2,
            "duration": 120.5
        }
        
        manager.create_run_summary(run_dir, summary_data)
        
        # Verify summary file exists
        summary_file = run_dir / "summary.json"
        assert summary_file.exists()
        
        # Verify content
        summary = json.loads(summary_file.read_text())
        assert summary["test_count"] == 10
        assert summary["passed"] == 8
        assert summary["failed"] == 2
        assert summary["run_id"] == "run_test"
        assert "timestamp" in summary


class TestArtifactsManagerIntegration:
    """Integration tests for ArtifactsManager."""
    
    def test_full_workflow(self, tmp_path):
        """Test complete artifacts collection workflow."""
        config = {
            'artifacts_dir': 'artifacts',
            'collect_node_logs': True,
            'collect_health_logs': False,
            'collect_crash_dumps': False,
            'retain_days': 30,
        }
        
        manager = ArtifactsManager(tmp_path, config)
        
        # Create run directory
        run_dir = manager.create_run_directory(run_id="integration_test")
        
        # Collect stage-env log
        log_file = tmp_path / "test.log"
        log_file.write_text("test content")
        manager.collect_stage_env_log(run_dir, log_file)
        
        # Create summary
        summary_data = {"status": "completed"}
        manager.create_run_summary(run_dir, summary_data)
        
        # Verify everything exists
        assert run_dir.exists()
        assert (run_dir / "stage-env-logs" / "test.log").exists()
        assert (run_dir / "summary.json").exists()
    
    def test_extract_file_from_container_error_handling(self, tmp_path):
        """Test that _extract_file_from_container handles errors."""
        config = {'artifacts_dir': 'artifacts'}
        manager = ArtifactsManager(tmp_path, config)
        
        mock_container = MagicMock()
        mock_container.get_archive.side_effect = Exception("Archive error")
        
        dest_path = tmp_path / "extracted_file"
        
        # Should not raise
        manager._extract_file_from_container(mock_container, "/src/file", dest_path)
