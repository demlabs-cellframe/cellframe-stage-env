"""
Base Core Manager for SquashFS base-core.sqfs creation and management.

The base core contains:
- Pool of pre-generated certificates
- Base config templates
- Clean initialized GDB + chains
- Docker image metadata
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from .utils import (
    run_command,
    check_squashfs_tools,
    calculate_file_checksum,
    get_cellframe_version,
    format_size,
    is_snapshot_expired,
    load_metadata,
    save_metadata,
)

logger = logging.getLogger(__name__)


class BaseCoreManager:
    """
    Manages base-core.sqfs creation, validation, and mounting.
    """
    
    def __init__(self, cache_dir: Path):
        """
        Initialize BaseCoreManager.
        
        Args:
            cache_dir: Path to cache directory (e.g., tests/stage-env/cache/)
        """
        self.cache_dir = Path(cache_dir)
        self.base_core_path = self.cache_dir / 'base-core.sqfs'
        self.base_core_metadata_path = self.cache_dir / 'base-core.sqfs.json'
        self.mount_point = Path('/mnt/cf-base-core')
        
    def exists(self) -> bool:
        """
        Check if base-core.sqfs exists.
        
        Returns:
            True if base-core.sqfs file exists
        """
        return self.base_core_path.exists()
    
    def is_valid(self, max_age_days: int = 90) -> bool:
        """
        Check if base-core.sqfs is valid and not expired.
        
        Args:
            max_age_days: Maximum age in days (default: 90)
            
        Returns:
            True if base core is valid
        """
        if not self.exists():
            logger.debug("Base core does not exist")
            return False
        
        metadata = load_metadata(self.base_core_metadata_path)
        if not metadata:
            logger.warning("Base core metadata not found or corrupted")
            return False
        
        # Check version
        current_version = get_cellframe_version()
        if metadata.get('version') != current_version and current_version != 'unknown':
            logger.info(f"Base core version mismatch: {metadata.get('version')} != {current_version}")
            return False
        
        # Check age
        created = metadata.get('created')
        if created and is_snapshot_expired(created, max_age_days):
            logger.info(f"Base core is older than {max_age_days} days")
            return False
        
        # Check checksum
        stored_checksum = metadata.get('checksum')
        if stored_checksum:
            actual_checksum = calculate_file_checksum(self.base_core_path)
            if actual_checksum != stored_checksum:
                logger.error("Base core checksum mismatch - file corrupted")
                return False
        
        return True
    
    def create(self, source_dir: Path, compression_level: int = 19, force: bool = False) -> bool:
        """
        Create base-core.sqfs from source directory.
        
        Args:
            source_dir: Directory containing base core components
            compression_level: zstd compression level (1-22, default: 19)
            force: Force recreation even if exists
            
        Returns:
            True if created successfully
        """
        if not check_squashfs_tools():
            raise RuntimeError("squashfs-tools not installed. Install with: apt-get install squashfs-tools")
        
        if self.exists() and not force:
            logger.info("Base core already exists, use force=True to recreate")
            return False
        
        if not source_dir.exists():
            raise ValueError(f"Source directory does not exist: {source_dir}")
        
        logger.info(f"Creating base-core.sqfs from {source_dir}")
        logger.info(f"Compression: zstd level {compression_level}")
        
        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Get uncompressed size
        result = run_command(['du', '-sb', str(source_dir)])
        size_uncompressed = int(result.stdout.split()[0])
        
        # Create SquashFS
        cmd = [
            'mksquashfs',
            str(source_dir),
            str(self.base_core_path),
            '-comp', 'zstd',
            '-Xcompression-level', str(compression_level),
            '-b', '1M',
            '-noappend',
            '-no-duplicates',
            '-no-exports',
        ]
        
        try:
            run_command(cmd, check=True)
            logger.info(f"Base core created: {self.base_core_path}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create base core: {e}")
            if self.base_core_path.exists():
                self.base_core_path.unlink()
            raise
        
        # Get compressed size
        size_compressed = self.base_core_path.stat().st_size
        
        # Calculate checksum
        checksum = calculate_file_checksum(self.base_core_path)
        
        # Save metadata
        metadata = {
            'version': get_cellframe_version(),
            'created': datetime.now().isoformat(),
            'size_uncompressed': size_uncompressed,
            'size_compressed': size_compressed,
            'compression_ratio': round(size_uncompressed / size_compressed, 2),
            'checksum': checksum,
            'compression_level': compression_level,
        }
        save_metadata(self.base_core_metadata_path, metadata)
        
        logger.info(f"Base core stats:")
        logger.info(f"  Uncompressed: {format_size(size_uncompressed)}")
        logger.info(f"  Compressed:   {format_size(size_compressed)}")
        logger.info(f"  Ratio:        {metadata['compression_ratio']}x")
        logger.info(f"  Checksum:     {checksum[:16]}...")
        
        return True
    
    def mount(self, readonly: bool = True) -> bool:
        """
        Mount base-core.sqfs to mount point.
        
        Args:
            readonly: Mount as read-only (default: True)
            
        Returns:
            True if mounted successfully
        """
        if not self.exists():
            raise ValueError("Base core does not exist")
        
        if self.is_mounted():
            logger.debug(f"Base core already mounted at {self.mount_point}")
            return True
        
        # Create mount point
        self.mount_point.mkdir(parents=True, exist_ok=True)
        
        # Mount SquashFS
        cmd = ['mount', '-t', 'squashfs', '-o', 'loop']
        if readonly:
            cmd.extend(['-o', 'ro'])
        cmd.extend([str(self.base_core_path), str(self.mount_point)])
        
        try:
            # Try with sudo if needed
            try:
                run_command(cmd, check=True)
            except subprocess.CalledProcessError:
                logger.debug("Mounting failed, trying with sudo")
                run_command(['sudo'] + cmd, check=True)
            
            logger.info(f"Base core mounted at {self.mount_point}")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to mount base core: {e}")
            raise
    
    def unmount(self) -> bool:
        """
        Unmount base-core.sqfs from mount point.
        
        Returns:
            True if unmounted successfully
        """
        if not self.is_mounted():
            logger.debug("Base core not mounted")
            return True
        
        try:
            # Try without sudo first
            try:
                run_command(['umount', str(self.mount_point)], check=True)
            except subprocess.CalledProcessError:
                logger.debug("Unmounting failed, trying with sudo")
                run_command(['sudo', 'umount', str(self.mount_point)], check=True)
            
            logger.info(f"Base core unmounted from {self.mount_point}")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to unmount base core: {e}")
            raise
    
    def is_mounted(self) -> bool:
        """
        Check if base-core.sqfs is currently mounted.
        
        Returns:
            True if mounted
        """
        try:
            result = run_command(['findmnt', str(self.mount_point)], check=False)
            return result.returncode == 0
        except Exception:
            return False
    
    def delete(self) -> bool:
        """
        Delete base-core.sqfs and metadata.
        
        Returns:
            True if deleted successfully
        """
        if self.is_mounted():
            self.unmount()
        
        deleted = False
        
        if self.base_core_path.exists():
            self.base_core_path.unlink()
            logger.info(f"Deleted base core: {self.base_core_path}")
            deleted = True
        
        if self.base_core_metadata_path.exists():
            self.base_core_metadata_path.unlink()
            logger.debug(f"Deleted metadata: {self.base_core_metadata_path}")
        
        return deleted
    
    def get_info(self) -> Optional[Dict[str, Any]]:
        """
        Get base core information.
        
        Returns:
            Dictionary with base core info or None if doesn't exist
        """
        if not self.exists():
            return None
        
        metadata = load_metadata(self.base_core_metadata_path)
        if not metadata:
            metadata = {}
        
        return {
            'path': str(self.base_core_path),
            'size': format_size(self.base_core_path.stat().st_size),
            'version': metadata.get('version', 'unknown'),
            'created': metadata.get('created', 'unknown'),
            'compression_ratio': metadata.get('compression_ratio', 0),
            'mounted': self.is_mounted(),
            'mount_point': str(self.mount_point) if self.is_mounted() else None,
            'valid': self.is_valid(),
        }

