"""
SquashFS + OverlayFS snapshot system for fast test environment startup.

This module provides:
- Base core management (base-core.sqfs)
- Topology snapshot management (per-topology .sqfs files)
- Fast start using OverlayFS
- Automatic snapshot creation and invalidation
"""

from .base_core import BaseCoreManager
from .topology_snapshot import TopologySnapshotManager
from .fast_start import FastStartManager

__all__ = [
    'BaseCoreManager',
    'TopologySnapshotManager',
    'FastStartManager',
]

