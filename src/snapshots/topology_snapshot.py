"""
Topology Snapshot Manager for creating and managing per-topology SquashFS snapshots.

Each topology gets its own .sqfs snapshot containing:
- Ready-to-use configs for this topology
- Initialized data volumes (after first successful start)
- Synced GDB state
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from .utils import (
    run_command,
    check_squashfs_tools,
    calculate_topology_hash,
    calculate_file_checksum,
    get_cellframe_version,
    format_size,
    is_snapshot_expired,
    load_metadata,
    save_metadata,
)

logger = logging.getLogger(__name__)


class TopologySnapshotManager:
    """
    Manages topology-specific SquashFS snapshots.
    """
    
    def __init__(self, cache_dir: Path):
        """
        Initialize TopologySnapshotManager.
        
        Args:
            cache_dir: Path to cache directory (e.g., tests/stage-env/cache/)
        """
        self.cache_dir = Path(cache_dir)
        self.snapshots_dir = self.cache_dir / 'snapshots'
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        
    def get_snapshot_path(self, topology_hash: str) -> Path:
        """
        Get path to snapshot file for topology hash.
        
        Args:
            topology_hash: SHA256 hash of topology
            
        Returns:
            Path to .sqfs file
        """
        return self.snapshots_dir / f'{topology_hash}.sqfs'
    
    def get_metadata_path(self, topology_hash: str) -> Path:
        """
        Get path to metadata file for topology hash.
        
        Args:
            topology_hash: SHA256 hash of topology
            
        Returns:
            Path to .json metadata file
        """
        return self.snapshots_dir / f'{topology_hash}.sqfs.json'
    
    def exists(self, topology_hash: str) -> bool:
        """
        Check if snapshot exists for topology.
        
        Args:
            topology_hash: SHA256 hash of topology
            
        Returns:
            True if snapshot exists
        """
        return self.get_snapshot_path(topology_hash).exists()
    
    def is_valid(self, topology_hash: str, max_age_days: int = 30) -> bool:
        """
        Check if snapshot is valid and not expired.
        
        Args:
            topology_hash: SHA256 hash of topology
            max_age_days: Maximum age in days (default: 30)
            
        Returns:
            True if snapshot is valid
        """
        if not self.exists(topology_hash):
            return False
        
        snapshot_path = self.get_snapshot_path(topology_hash)
        metadata_path = self.get_metadata_path(topology_hash)
        
        metadata = load_metadata(metadata_path)
        if not metadata:
            logger.warning(f"Snapshot metadata not found: {metadata_path}")
            return False
        
        # Check topology hash match
        if metadata.get('topology_hash') != topology_hash:
            logger.error(f"Topology hash mismatch in metadata")
            return False
        
        # Check version
        current_version = get_cellframe_version()
        if metadata.get('cellframe_version') != current_version and current_version != 'unknown':
            logger.info(f"Snapshot version mismatch: {metadata.get('cellframe_version')} != {current_version}")
            return False
        
        # Check age
        created = metadata.get('created')
        if created and is_snapshot_expired(created, max_age_days):
            logger.info(f"Snapshot is older than {max_age_days} days")
            return False
        
        # Check checksum if available
        stored_checksum = metadata.get('checksum')
        if stored_checksum:
            actual_checksum = calculate_file_checksum(snapshot_path)
            if actual_checksum != stored_checksum:
                logger.error("Snapshot checksum mismatch - file corrupted")
                return False
        
        return True
    
    def create(self, 
               topology_config: Dict[str, Any],
               source_dir: Path, 
               compression_level: int = 15,
               force: bool = False) -> str:
        """
        Create snapshot from source directory.
        
        Args:
            topology_config: Topology configuration dictionary
            source_dir: Directory containing topology data (configs + data volumes)
            compression_level: zstd compression level (1-22, default: 15)
            force: Force recreation even if exists
            
        Returns:
            Topology hash
        """
        if not check_squashfs_tools():
            raise RuntimeError("squashfs-tools not installed. Install with: apt-get install squashfs-tools")
        
        if not source_dir.exists():
            raise ValueError(f"Source directory does not exist: {source_dir}")
        
        # Calculate topology hash
        topology_hash = calculate_topology_hash(topology_config)
        snapshot_path = self.get_snapshot_path(topology_hash)
        metadata_path = self.get_metadata_path(topology_hash)
        
        if self.exists(topology_hash) and not force:
            logger.info(f"Snapshot already exists: {topology_hash[:16]}..., use force=True to recreate")
            return topology_hash
        
        logger.info(f"Creating topology snapshot: {topology_hash[:16]}...")
        logger.info(f"Source: {source_dir}")
        logger.info(f"Compression: zstd level {compression_level}")
        
        # Get uncompressed size
        result = run_command(['du', '-sb', str(source_dir)])
        size_uncompressed = int(result.stdout.split()[0])
        
        # Create SquashFS
        cmd = [
            'mksquashfs',
            str(source_dir),
            str(snapshot_path),
            '-comp', 'zstd',
            '-Xcompression-level', str(compression_level),
            '-b', '1M',
            '-noappend',
        ]
        
        try:
            run_command(cmd, check=True)
            logger.info(f"Snapshot created: {snapshot_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create snapshot: {e}")
            if snapshot_path.exists():
                snapshot_path.unlink()
            raise
        
        # Get compressed size
        size_compressed = snapshot_path.stat().st_size
        
        # Calculate checksum
        checksum = calculate_file_checksum(snapshot_path)
        
        # Save metadata
        metadata = {
            'topology_hash': topology_hash,
            'node_count': topology_config.get('node_count', len(topology_config.get('nodes', []))),
            'consensus_type': topology_config.get('consensus_type', 'unknown'),
            'network_type': topology_config.get('network_type', 'unknown'),
            'chain_type': topology_config.get('chain_type', 'unknown'),
            'cellframe_version': get_cellframe_version(),
            'created': datetime.now().isoformat(),
            'size_uncompressed': size_uncompressed,
            'size_compressed': size_compressed,
            'compression_ratio': round(size_uncompressed / size_compressed, 2),
            'checksum': checksum,
            'compression_level': compression_level,
        }
        save_metadata(metadata_path, metadata)
        
        logger.info(f"Snapshot stats:")
        logger.info(f"  Hash:         {topology_hash[:16]}...")
        logger.info(f"  Nodes:        {metadata['node_count']}")
        logger.info(f"  Consensus:    {metadata['consensus_type']}")
        logger.info(f"  Uncompressed: {format_size(size_uncompressed)}")
        logger.info(f"  Compressed:   {format_size(size_compressed)}")
        logger.info(f"  Ratio:        {metadata['compression_ratio']}x")
        
        return topology_hash
    
    def delete(self, topology_hash: str) -> bool:
        """
        Delete snapshot and metadata.
        
        Args:
            topology_hash: SHA256 hash of topology
            
        Returns:
            True if deleted successfully
        """
        snapshot_path = self.get_snapshot_path(topology_hash)
        metadata_path = self.get_metadata_path(topology_hash)
        
        deleted = False
        
        if snapshot_path.exists():
            snapshot_path.unlink()
            logger.info(f"Deleted snapshot: {topology_hash[:16]}...")
            deleted = True
        
        if metadata_path.exists():
            metadata_path.unlink()
            logger.debug(f"Deleted metadata: {metadata_path}")
        
        return deleted
    
    def list_snapshots(self) -> List[Dict[str, Any]]:
        """
        List all available snapshots with metadata.
        
        Returns:
            List of dictionaries with snapshot info
        """
        snapshots = []
        
        for sqfs_file in self.snapshots_dir.glob('*.sqfs'):
            # Skip if it's base-core.sqfs
            if sqfs_file.name == 'base-core.sqfs':
                continue
            
            topology_hash = sqfs_file.stem
            metadata_path = self.get_metadata_path(topology_hash)
            
            metadata = load_metadata(metadata_path)
            if not metadata:
                metadata = {}
            
            snapshot_info = {
                'topology_hash': topology_hash,
                'topology_hash_short': topology_hash[:16],
                'path': str(sqfs_file),
                'size': format_size(sqfs_file.stat().st_size),
                'size_bytes': sqfs_file.stat().st_size,
                'node_count': metadata.get('node_count', 'unknown'),
                'consensus_type': metadata.get('consensus_type', 'unknown'),
                'version': metadata.get('cellframe_version', 'unknown'),
                'created': metadata.get('created', 'unknown'),
                'compression_ratio': metadata.get('compression_ratio', 0),
                'valid': self.is_valid(topology_hash),
            }
            
            snapshots.append(snapshot_info)
        
        # Sort by creation date (newest first)
        snapshots.sort(key=lambda x: x['created'], reverse=True)
        
        return snapshots
    
    def clean_expired(self, max_age_days: int = 30) -> int:
        """
        Delete expired snapshots.
        
        Args:
            max_age_days: Maximum age in days (default: 30)
            
        Returns:
            Number of snapshots deleted
        """
        deleted_count = 0
        
        for snapshot in self.list_snapshots():
            topology_hash = snapshot['topology_hash']
            
            if not self.is_valid(topology_hash, max_age_days):
                logger.info(f"Deleting expired snapshot: {topology_hash[:16]}...")
                self.delete(topology_hash)
                deleted_count += 1
        
        return deleted_count
    
    def get_info(self, topology_hash: str) -> Optional[Dict[str, Any]]:
        """
        Get snapshot information.
        
        Args:
            topology_hash: SHA256 hash of topology
            
        Returns:
            Dictionary with snapshot info or None if doesn't exist
        """
        if not self.exists(topology_hash):
            return None
        
        snapshot_path = self.get_snapshot_path(topology_hash)
        metadata_path = self.get_metadata_path(topology_hash)
        
        metadata = load_metadata(metadata_path)
        if not metadata:
            metadata = {}
        
        return {
            'topology_hash': topology_hash,
            'path': str(snapshot_path),
            'size': format_size(snapshot_path.stat().st_size),
            'node_count': metadata.get('node_count', 'unknown'),
            'consensus_type': metadata.get('consensus_type', 'unknown'),
            'version': metadata.get('cellframe_version', 'unknown'),
            'created': metadata.get('created', 'unknown'),
            'compression_ratio': metadata.get('compression_ratio', 0),
            'valid': self.is_valid(topology_hash),
            'metadata': metadata,
        }
    
    def get_total_size(self) -> int:
        """
        Get total size of all snapshots in bytes.
        
        Returns:
            Total size in bytes
        """
        total_size = 0
        
        for sqfs_file in self.snapshots_dir.glob('*.sqfs'):
            if sqfs_file.name != 'base-core.sqfs':
                total_size += sqfs_file.stat().st_size
        
        return total_size

