"""Unit tests for src/snapshots/ module."""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestSnapshotManager:
    """Test SnapshotManager."""
    
    def test_snapshot_manager_import(self):
        from src.snapshots.manager import SnapshotManager
        assert SnapshotManager is not None
    
    def test_snapshot_manager_init(self, tmp_path):
        from src.snapshots.manager import SnapshotManager
        manager = SnapshotManager(tmp_path)
        assert manager.base_path == tmp_path


class TestSnapshotsIntegration:
    """Integration tests."""
    
    def test_snapshots_module_importable(self):
        from src.snapshots import manager
        assert manager is not None
