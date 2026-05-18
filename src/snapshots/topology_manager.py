"""
Topology Snapshot Manager - sync CLI wrapper for snapshot operations.

Provides synchronous interface for CLI commands to list, delete, and inspect
topology snapshots without requiring async context.
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
import json
import time
from datetime import datetime

from src.utils.logger import get_logger

logger = get_logger(__name__)


def format_size(size_bytes: int) -> str:
    """Format size in bytes to human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


class TopologySnapshotManager:
    """
    Synchronous manager for topology snapshots.
    
    Provides CLI-friendly interface for snapshot operations:
    - list_snapshots(): Get all available snapshots with metadata
    - delete_snapshot(hash): Delete specific snapshot
    - delete_all(): Delete all snapshots
    - get_snapshot_info(hash): Get detailed snapshot info
    - get_total_size(): Get total size of all snapshots
    """
    
    SNAPSHOT_VERSION = "1.0"
    
    def __init__(self, snapshots_dir: Path):
        """
        Initialize topology snapshot manager.
        
        Args:
            snapshots_dir: Path to snapshots directory
        """
        self.snapshots_dir = Path(snapshots_dir)
        
        logger.debug("topology_snapshot_manager_initialized",
                    snapshots_dir=str(self.snapshots_dir))
    
    def list_snapshots(self) -> List[Dict[str, Any]]:
        """
        List all available topology snapshots.
        
        Returns:
            List of snapshot info dictionaries with keys:
            - topology_hash: Full hash
            - topology_hash_short: Short hash for display
            - node_count: Number of nodes
            - consensus_type: Consensus type
            - size: Human-readable size
            - size_bytes: Size in bytes
            - version: Snapshot version
            - created: Creation timestamp
            - valid: Whether snapshot is valid
        """
        snapshots = []
        
        if not self.snapshots_dir.exists():
            return snapshots
        
        for snapshot_dir in self.snapshots_dir.iterdir():
            if not snapshot_dir.is_dir():
                continue
            
            info = self._read_snapshot_info(snapshot_dir)
            if info:
                snapshots.append(info)
        
        # Sort by creation time (newest first)
        snapshots.sort(key=lambda x: x.get('created', ''), reverse=True)
        
        return snapshots
    
    def _read_snapshot_info(self, snapshot_dir: Path) -> Optional[Dict[str, Any]]:
        """Read snapshot metadata from directory."""
        metadata_file = snapshot_dir / "metadata.json"
        
        # Calculate size
        size_bytes = self._get_dir_size(snapshot_dir)
        
        # Check for metadata file
        if metadata_file.exists():
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                
                return {
                    'topology_hash': snapshot_dir.name,
                    'topology_hash_short': snapshot_dir.name[:12],
                    'node_count': metadata.get('node_count', 0),
                    'consensus_type': metadata.get('consensus_type', 'unknown'),
                    'size': format_size(size_bytes),
                    'size_bytes': size_bytes,
                    'version': metadata.get('version', self.SNAPSHOT_VERSION),
                    'created': metadata.get('created', self._get_dir_mtime(snapshot_dir)),
                    'valid': self._validate_snapshot(snapshot_dir),
                    'network': metadata.get('network', 'stagenet'),
                    'nodes': metadata.get('nodes', []),
                }
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("snapshot_metadata_read_error",
                             snapshot=snapshot_dir.name,
                             error=str(e))
        
        # Fallback: infer from directory structure
        return {
            'topology_hash': snapshot_dir.name,
            'topology_hash_short': snapshot_dir.name[:12],
            'node_count': self._count_nodes(snapshot_dir),
            'consensus_type': 'unknown',
            'size': format_size(size_bytes),
            'size_bytes': size_bytes,
            'version': self.SNAPSHOT_VERSION,
            'created': self._get_dir_mtime(snapshot_dir),
            'valid': self._validate_snapshot(snapshot_dir),
        }
    
    def _get_dir_size(self, path: Path) -> int:
        """Calculate total size of directory."""
        total = 0
        try:
            for entry in path.rglob('*'):
                if entry.is_file():
                    total += entry.stat().st_size
        except (OSError, PermissionError):
            pass
        return total
    
    def _get_dir_mtime(self, path: Path) -> str:
        """Get directory modification time as ISO string."""
        try:
            mtime = path.stat().st_mtime
            return datetime.fromtimestamp(mtime).isoformat()
        except OSError:
            return datetime.now().isoformat()
    
    def _count_nodes(self, snapshot_dir: Path) -> int:
        """Count number of node directories in snapshot."""
        data_dir = snapshot_dir / "data"
        if not data_dir.exists():
            return 0
        
        count = 0
        for entry in data_dir.iterdir():
            if entry.is_dir() and entry.name.startswith('node'):
                count += 1
        return count
    
    def _validate_snapshot(self, snapshot_dir: Path) -> bool:
        """Validate snapshot integrity."""
        # Basic validation: check required directories exist
        data_dir = snapshot_dir / "data"
        configs_dir = snapshot_dir / "configs"
        
        if not data_dir.exists():
            return False
        
        # Check at least one node directory exists
        node_dirs = list(data_dir.glob("node*"))
        if not node_dirs:
            return False
        
        return True
    
    def get_snapshot_info(self, topology_hash: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific snapshot.
        
        Args:
            topology_hash: Full or partial topology hash
            
        Returns:
            Snapshot info dictionary or None if not found
        """
        snapshot_dir = self._find_snapshot_dir(topology_hash)
        if not snapshot_dir:
            return None
        
        return self._read_snapshot_info(snapshot_dir)
    
    def _find_snapshot_dir(self, topology_hash: str) -> Optional[Path]:
        """Find snapshot directory by full or partial hash."""
        if not self.snapshots_dir.exists():
            return None
        
        # Try exact match first
        exact_path = self.snapshots_dir / topology_hash
        if exact_path.exists():
            return exact_path
        
        # Try prefix match
        for snapshot_dir in self.snapshots_dir.iterdir():
            if snapshot_dir.is_dir() and snapshot_dir.name.startswith(topology_hash):
                return snapshot_dir
        
        return None
    
    def delete_snapshot(self, topology_hash: str) -> bool:
        """
        Delete a specific snapshot.
        
        Args:
            topology_hash: Full or partial topology hash
            
        Returns:
            True if deleted successfully
        """
        snapshot_dir = self._find_snapshot_dir(topology_hash)
        if not snapshot_dir:
            logger.warning("snapshot_not_found", hash=topology_hash)
            return False
        
        try:
            import shutil
            shutil.rmtree(snapshot_dir)
            logger.info("snapshot_deleted", hash=topology_hash, path=str(snapshot_dir))
            return True
        except (OSError, PermissionError) as e:
            logger.error("snapshot_delete_failed", hash=topology_hash, error=str(e))
            return False
    
    def delete_all(self) -> int:
        """
        Delete all snapshots.
        
        Returns:
            Number of snapshots deleted
        """
        if not self.snapshots_dir.exists():
            return 0
        
        deleted = 0
        for snapshot_dir in list(self.snapshots_dir.iterdir()):
            if snapshot_dir.is_dir():
                try:
                    import shutil
                    shutil.rmtree(snapshot_dir)
                    deleted += 1
                    logger.debug("snapshot_deleted", path=str(snapshot_dir))
                except (OSError, PermissionError) as e:
                    logger.warning("snapshot_delete_failed", path=str(snapshot_dir), error=str(e))
        
        logger.info("all_snapshots_deleted", count=deleted)
        return deleted
    
    def get_total_size(self) -> int:
        """
        Get total size of all snapshots.
        
        Returns:
            Total size in bytes
        """
        if not self.snapshots_dir.exists():
            return 0
        
        return self._get_dir_size(self.snapshots_dir)
