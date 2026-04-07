"""
Snapshot system for fast environment restoration.

Backend is auto-detected at startup based on available system tools:
  squashfs  > filesystem (rsync) > recreate (baseline)
"""

from .manager import SnapshotManager, SnapshotMode, detect_best_mode
from .base import BaseSnapshot, SNAPSHOT_EXCLUDE_PATTERNS
from .recreate import RecreateSnapshot
from .filesystem import FilesystemSnapshot
from .squashfs import SquashfsSnapshot

__all__ = [
    'SnapshotManager',
    'SnapshotMode',
    'detect_best_mode',
    'BaseSnapshot',
    'SNAPSHOT_EXCLUDE_PATTERNS',
    'RecreateSnapshot',
    'FilesystemSnapshot',
    'SquashfsSnapshot',
]
