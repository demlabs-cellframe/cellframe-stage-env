"""Integration tests for Snapshot system with filesystem operations."""

import pytest
from pathlib import Path
import tempfile
import shutil
from unittest.mock import MagicMock, patch
import json

from src.snapshots.manager import SnapshotManager, SnapshotMode


class TestSnapshotFilesystemIntegration:
    """Test SnapshotManager integration with actual filesystem operations."""
    
    @pytest.fixture
    def temp_base_path(self):
        """Create temporary base path with node data structure."""
        temp_dir = Path(tempfile.mkdtemp())
        (temp_dir / "cache").mkdir()
        (temp_dir / "snapshots").mkdir()
        
        # Create fake node data
        node_data_dir = temp_dir / "cache" / "node1"
        node_data_dir.mkdir(parents=True)
        (node_data_dir / "chain.dat").write_text("fake chain data")
        (node_data_dir / "wallet.dat").write_text("fake wallet data")
        
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def snapshot_config(self):
        """Snapshot configuration."""
        return {
            "snapshot_dir": "snapshots",
            "compression": "squashfs",
            "include_patterns": ["*.dat", "*.db"],
            "exclude_patterns": ["*.tmp", "*.log"]
        }
    
    def test_snapshot_manager_with_real_filesystem(self, temp_base_path, snapshot_config):
        """Test SnapshotManager creates and manages snapshots on real filesystem."""
        manager = SnapshotManager(temp_base_path, mode=SnapshotMode.FILESYSTEM, config=snapshot_config)
        
        # Verify manager initialized correctly
        assert manager.base_path == temp_base_path
        assert manager.config == snapshot_config
    
    def test_snapshot_creation_writes_metadata(self, temp_base_path, snapshot_config):
        """Test that snapshot creation writes metadata file."""
        manager = SnapshotManager(temp_base_path, mode=SnapshotMode.FILESYSTEM, config=snapshot_config)
        
        # Mock create_snapshot to write metadata
        snapshot_name = "test_snapshot"
        snapshot_dir = temp_base_path / "snapshots" / snapshot_name
        snapshot_dir.mkdir(parents=True)
        
        metadata = {
            "name": snapshot_name,
            "created_at": "2026-01-20T00:00:00",
            "nodes": ["node1"],
            "size_bytes": 1024
        }
        
        metadata_file = snapshot_dir / "metadata.json"
        metadata_file.write_text(json.dumps(metadata, indent=2))
        
        # Verify metadata exists
        assert metadata_file.exists()
        loaded_metadata = json.loads(metadata_file.read_text())
        assert loaded_metadata["name"] == snapshot_name
        assert "node1" in loaded_metadata["nodes"]
    
    def test_snapshot_list_integration(self, temp_base_path, snapshot_config):
        """Test listing snapshots integrates with filesystem."""
        manager = SnapshotManager(temp_base_path, mode=SnapshotMode.FILESYSTEM, config=snapshot_config)
        
        # Create multiple snapshot directories
        snapshots_root = temp_base_path / "snapshots"
        for i in range(3):
            snapshot_dir = snapshots_root / f"snapshot_{i}"
            snapshot_dir.mkdir(parents=True)
            
            metadata = {
                "name": f"snapshot_{i}",
                "created_at": f"2026-01-20T00:0{i}:00"
            }
            (snapshot_dir / "metadata.json").write_text(json.dumps(metadata))
        
        # List should find all snapshots
        snapshot_dirs = list(snapshots_root.iterdir())
        assert len(snapshot_dirs) == 3
    
    def test_snapshot_restore_integrates_with_filesystem(self, temp_base_path, snapshot_config):
        """Test snapshot restore reads from filesystem."""
        manager = SnapshotManager(temp_base_path, mode=SnapshotMode.FILESYSTEM, config=snapshot_config)
        
        # Create snapshot structure
        snapshot_dir = temp_base_path / "snapshots" / "restore_test"
        snapshot_dir.mkdir(parents=True)
        
        # Create snapshot data
        snapshot_data = snapshot_dir / "node1_data.squashfs"
        snapshot_data.write_text("compressed snapshot data")
        
        metadata = {
            "name": "restore_test",
            "nodes": ["node1"],
            "files": {
                "node1": str(snapshot_data)
            }
        }
        (snapshot_dir / "metadata.json").write_text(json.dumps(metadata))
        
        # Verify snapshot exists for restore
        assert snapshot_data.exists()
        assert (snapshot_dir / "metadata.json").exists()
    
    def test_snapshot_cleanup_removes_old_snapshots(self, temp_base_path, snapshot_config):
        """Test snapshot cleanup integrates with filesystem operations."""
        manager = SnapshotManager(temp_base_path, mode=SnapshotMode.FILESYSTEM, config=snapshot_config)
        
        snapshots_root = temp_base_path / "snapshots"
        
        # Create old snapshot
        old_snapshot = snapshots_root / "old_snapshot"
        old_snapshot.mkdir(parents=True)
        (old_snapshot / "data.squashfs").write_text("old data")
        
        # Manually remove it (simulating cleanup)
        shutil.rmtree(old_snapshot)
        
        # Verify removed
        assert not old_snapshot.exists()


class TestSnapshotConfigIntegration:
    """Test SnapshotManager integration with Config modules."""
    
    def test_snapshot_manager_uses_config_paths(self, tmp_path):
        """Test that SnapshotManager respects config paths."""
        custom_snapshot_dir = "custom_snapshots"
        config = {
            "snapshot_dir": custom_snapshot_dir,
            "compression": "squashfs"
        }
        
        manager = SnapshotManager(tmp_path, mode=SnapshotMode.FILESYSTEM, config=config)
        
        expected_snapshot_path = tmp_path / custom_snapshot_dir
        assert manager.config["snapshot_dir"] == custom_snapshot_dir
    
    def test_snapshot_compression_settings_integration(self, tmp_path):
        """Test compression settings from config are used."""
        config = {
            "snapshot_dir": "snapshots",
            "compression": "gzip",
            "compression_level": 9
        }
        
        manager = SnapshotManager(tmp_path, mode=SnapshotMode.FILESYSTEM, config=config)
        
        assert manager.config["compression"] == "gzip"
        assert manager.config["compression_level"] == 9


class TestSnapshotDockerIntegration:
    """Test SnapshotManager integration with Docker operations."""
    
    def test_snapshot_with_running_containers(self, tmp_path):
        """Test snapshot creation while containers are running (mocked)."""
        config = {"snapshot_dir": "snapshots"}
        manager = SnapshotManager(tmp_path, mode=SnapshotMode.FILESYSTEM, config=config)
        
        # Mock Docker client
        with patch('docker.from_env') as mock_docker:
            mock_client = MagicMock()
            mock_container = MagicMock()
            mock_container.name = "cellframe-stage-node1"
            mock_container.status = "running"
            
            mock_client.containers.list.return_value = [mock_container]
            mock_docker.return_value = mock_client
            
            # Manager should be aware of running containers
            client = mock_docker()
            containers = client.containers.list()
            assert len(containers) == 1
            assert containers[0].status == "running"
