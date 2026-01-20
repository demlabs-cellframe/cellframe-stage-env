"""Unit tests for src/snapshots/manager.py."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

class TestSnapshotManager:
    """Test SnapshotManager."""
    
    def test_import_snapshot_manager(self):
        """Test importing SnapshotManager."""
        from src.snapshots.manager import SnapshotManager
        assert SnapshotManager is not None
    
    def test_snapshot_manager_init(self, tmp_path):
        """Test SnapshotManager initialization."""
        from src.snapshots.manager import SnapshotManager
        manager = SnapshotManager(tmp_path / "stage-env")
        assert manager is not None
