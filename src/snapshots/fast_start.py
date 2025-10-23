"""
Fast Start Manager for rapid startup using OverlayFS over SquashFS snapshots.

Provides:
- OverlayFS mounting over SquashFS snapshots
- Automatic cleanup of overlay filesystems
- Mount/unmount management
"""

import logging
import subprocess
import uuid
from pathlib import Path
from typing import Optional, Dict, Any

from .utils import run_command, check_overlayfs_support

logger = logging.getLogger(__name__)


class FastStartManager:
    """
    Manages fast startup using OverlayFS over SquashFS snapshots.
    """
    
    def __init__(self, cache_dir: Path):
        """
        Initialize FastStartManager.
        
        Args:
            cache_dir: Path to cache directory (e.g., tests/stage-env/cache/)
        """
        self.cache_dir = Path(cache_dir)
        self.active_dir = self.cache_dir / 'active'
        self.active_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate unique run ID for this session
        self.run_id = str(uuid.uuid4())[:8]
        
        # Overlay directories
        self.overlay_base = Path(f'/tmp/cf-overlay-{self.run_id}')
        self.overlay_upper = self.overlay_base / 'upper'
        self.overlay_work = self.overlay_base / 'work'
        
        # Mount point for SquashFS snapshot
        self.snapshot_mount = Path(f'/mnt/cf-snapshot-{self.run_id}')
        
        self._is_mounted = False
        self._snapshot_path: Optional[Path] = None
    
    def start_from_snapshot(self, snapshot_path: Path) -> bool:
        """
        Start from SquashFS snapshot using OverlayFS.
        
        Args:
            snapshot_path: Path to .sqfs snapshot file
            
        Returns:
            True if started successfully
        """
        if not snapshot_path.exists():
            raise ValueError(f"Snapshot does not exist: {snapshot_path}")
        
        if self._is_mounted:
            logger.warning("Already mounted, unmounting first")
            self.cleanup()
        
        logger.info(f"Starting from snapshot: {snapshot_path.name}")
        
        # Check OverlayFS support
        if not check_overlayfs_support():
            logger.warning("OverlayFS module not loaded, attempting to load")
            try:
                run_command(['sudo', 'modprobe', 'overlay'], check=True)
            except subprocess.CalledProcessError:
                raise RuntimeError("OverlayFS not supported on this system")
        
        # Step 1: Mount SquashFS snapshot
        logger.debug(f"Mounting snapshot to {self.snapshot_mount}")
        self._mount_snapshot(snapshot_path)
        
        # Step 2: Prepare overlay directories
        logger.debug(f"Preparing overlay directories in {self.overlay_base}")
        self._prepare_overlay()
        
        # Step 3: Mount OverlayFS
        logger.debug(f"Mounting OverlayFS to {self.active_dir}")
        self._mount_overlay()
        
        self._is_mounted = True
        self._snapshot_path = snapshot_path
        
        logger.info(f"Fast start complete: {self.active_dir}")
        logger.info(f"  Lower layer: {self.snapshot_mount} (read-only)")
        logger.info(f"  Upper layer: {self.overlay_upper} (tmpfs)")
        
        return True
    
    def _mount_snapshot(self, snapshot_path: Path) -> None:
        """
        Mount SquashFS snapshot read-only.
        
        Args:
            snapshot_path: Path to .sqfs file
        """
        # Create mount point
        self.snapshot_mount.mkdir(parents=True, exist_ok=True)
        
        # Mount SquashFS
        cmd = [
            'mount',
            '-t', 'squashfs',
            '-o', 'loop,ro',
            str(snapshot_path),
            str(self.snapshot_mount)
        ]
        
        try:
            # Try without sudo first
            try:
                run_command(cmd, check=True)
            except subprocess.CalledProcessError:
                logger.debug("Mounting failed, trying with sudo")
                run_command(['sudo'] + cmd, check=True)
                
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to mount snapshot: {e}")
            raise
    
    def _prepare_overlay(self) -> None:
        """
        Prepare OverlayFS directories (upperdir and workdir).
        """
        # Create overlay directories
        self.overlay_base.mkdir(parents=True, exist_ok=True)
        self.overlay_upper.mkdir(parents=True, exist_ok=True)
        self.overlay_work.mkdir(parents=True, exist_ok=True)
        
        logger.debug(f"Overlay directories created:")
        logger.debug(f"  upper: {self.overlay_upper}")
        logger.debug(f"  work:  {self.overlay_work}")
    
    def _mount_overlay(self) -> None:
        """
        Mount OverlayFS combining snapshot (lower) and overlay (upper).
        """
        # Ensure active directory exists and is empty
        if self.active_dir.exists() and any(self.active_dir.iterdir()):
            # If already mounted, unmount first
            if self._is_overlay_mounted():
                self._unmount_overlay()
        
        self.active_dir.mkdir(parents=True, exist_ok=True)
        
        # Mount OverlayFS
        cmd = [
            'mount',
            '-t', 'overlay',
            'overlay',
            '-o', f'lowerdir={self.snapshot_mount},'
                  f'upperdir={self.overlay_upper},'
                  f'workdir={self.overlay_work}',
            str(self.active_dir)
        ]
        
        try:
            # Try without sudo first
            try:
                run_command(cmd, check=True)
            except subprocess.CalledProcessError:
                logger.debug("Mounting overlay failed, trying with sudo")
                run_command(['sudo'] + cmd, check=True)
                
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to mount overlay: {e}")
            # Cleanup snapshot mount
            self._unmount_snapshot()
            raise
    
    def _is_overlay_mounted(self) -> bool:
        """
        Check if OverlayFS is mounted.
        
        Returns:
            True if mounted
        """
        try:
            result = run_command(['findmnt', str(self.active_dir)], check=False)
            return result.returncode == 0
        except Exception:
            return False
    
    def _is_snapshot_mounted(self) -> bool:
        """
        Check if snapshot is mounted.
        
        Returns:
            True if mounted
        """
        try:
            result = run_command(['findmnt', str(self.snapshot_mount)], check=False)
            return result.returncode == 0
        except Exception:
            return False
    
    def _unmount_overlay(self) -> None:
        """
        Unmount OverlayFS.
        """
        if not self._is_overlay_mounted():
            logger.debug("Overlay not mounted")
            return
        
        try:
            # Try without sudo first
            try:
                run_command(['umount', str(self.active_dir)], check=True)
            except subprocess.CalledProcessError:
                logger.debug("Unmounting overlay failed, trying with sudo")
                run_command(['sudo', 'umount', str(self.active_dir)], check=True)
            
            logger.debug(f"Overlay unmounted from {self.active_dir}")
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to unmount overlay: {e}")
            # Try force unmount
            try:
                run_command(['sudo', 'umount', '-f', str(self.active_dir)], check=False)
            except Exception:
                pass
    
    def _unmount_snapshot(self) -> None:
        """
        Unmount SquashFS snapshot.
        """
        if not self._is_snapshot_mounted():
            logger.debug("Snapshot not mounted")
            return
        
        try:
            # Try without sudo first
            try:
                run_command(['umount', str(self.snapshot_mount)], check=True)
            except subprocess.CalledProcessError:
                logger.debug("Unmounting snapshot failed, trying with sudo")
                run_command(['sudo', 'umount', str(self.snapshot_mount)], check=True)
            
            logger.debug(f"Snapshot unmounted from {self.snapshot_mount}")
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to unmount snapshot: {e}")
            # Try force unmount
            try:
                run_command(['sudo', 'umount', '-f', str(self.snapshot_mount)], check=False)
            except Exception:
                pass
    
    def cleanup(self) -> bool:
        """
        Cleanup: unmount overlay and snapshot, remove temporary directories.
        
        Returns:
            True if cleaned up successfully
        """
        if not self._is_mounted:
            logger.debug("Not mounted, nothing to cleanup")
            return True
        
        logger.info("Cleaning up fast start environment")
        
        # Step 1: Unmount overlay
        self._unmount_overlay()
        
        # Step 2: Unmount snapshot
        self._unmount_snapshot()
        
        # Step 3: Remove overlay directories
        if self.overlay_base.exists():
            try:
                import shutil
                shutil.rmtree(self.overlay_base)
                logger.debug(f"Removed overlay directories: {self.overlay_base}")
            except Exception as e:
                logger.warning(f"Failed to remove overlay directories: {e}")
        
        # Step 4: Remove snapshot mount point
        if self.snapshot_mount.exists():
            try:
                self.snapshot_mount.rmdir()
                logger.debug(f"Removed mount point: {self.snapshot_mount}")
            except Exception as e:
                logger.warning(f"Failed to remove mount point: {e}")
        
        self._is_mounted = False
        self._snapshot_path = None
        
        logger.info("Cleanup complete")
        return True
    
    def get_info(self) -> Dict[str, Any]:
        """
        Get current fast start environment info.
        
        Returns:
            Dictionary with environment info
        """
        return {
            'run_id': self.run_id,
            'mounted': self._is_mounted,
            'snapshot_path': str(self._snapshot_path) if self._snapshot_path else None,
            'active_dir': str(self.active_dir),
            'snapshot_mount': str(self.snapshot_mount),
            'overlay_upper': str(self.overlay_upper),
            'overlay_work': str(self.overlay_work),
            'overlay_mounted': self._is_overlay_mounted(),
            'snapshot_mounted': self._is_snapshot_mounted(),
        }
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup."""
        self.cleanup()
        return False

