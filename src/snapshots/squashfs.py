"""
Squashfs snapshot mode - read-only image with overlay filesystem.

This mode creates compressed read-only images using squashfs and uses
overlay filesystem for writes. Provides maximum speed with minimal overhead.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import os
import stat
from pathlib import Path
from typing import Dict, Any, Optional, List
import subprocess

from src.utils.logger import get_logger
from .base import BaseSnapshot, SNAPSHOT_EXCLUDE_PATTERNS

logger = get_logger(__name__)


class SquashfsSnapshot(BaseSnapshot):
    """
    Squashfs mode - read-only image with overlay.
    
    Creates compressed read-only squashfs images of clean state.
    Uses overlay filesystem to provide writable layer on top of read-only base.
    
    Estimated performance: ~2s for snapshot creation, ~1s for restore.
    Compression optional (can be disabled for even faster creation).
    """
    
    def __init__(self, base_path: Path, config: Dict[str, Any]):
        """
        Initialize squashfs snapshot handler.
        
        Args:
            base_path: Base path to stage-env directory
            config: Configuration dictionary
            
        Raises:
            RuntimeError: If squashfs tools are not available (fail-fast)
        """
        super().__init__(base_path, config)
        
        # Check if required tools are available
        self.has_mksquashfs = self._check_tool("mksquashfs")
        self.has_unsquashfs = self._check_tool("unsquashfs")
        self.has_overlayfs = self._check_overlayfs()
        
        # Fail-fast: squashfs mode requires tools to be installed
        if not self.has_mksquashfs or not self.has_unsquashfs:
            missing = []
            if not self.has_mksquashfs:
                missing.append("mksquashfs")
            if not self.has_unsquashfs:
                missing.append("unsquashfs")
            
            error_msg = (
                f"Squashfs mode selected but required tools are missing: {', '.join(missing)}. "
                f"Install squashfs-tools package: sudo apt install squashfs-tools"
            )
            logger.error("squashfs_tools_missing",
                        has_mksquashfs=self.has_mksquashfs,
                        has_unsquashfs=self.has_unsquashfs,
                        missing=missing)
            raise RuntimeError(error_msg)
        
        # Compression mode from config
        compression = config.get('squashfs_compression', 'none')
        self.compression = compression if compression != 'none' else None
        
        # Overlay directories
        self.overlay_base = self.snapshots_path / ".overlays"
        self.overlay_base.mkdir(parents=True, exist_ok=True)
        
        logger.info("squashfs_mode_initialized",
                   tools_available=True,
                   overlayfs_available=self.has_overlayfs,
                   compression=self.compression or "none")
    
    def _check_tool(self, tool: str) -> bool:
        """Check if a command-line tool is available."""
        try:
            # Try to run the tool - squashfs tools use -version (not --version)
            result = subprocess.run(
                [tool, "-version"],
                capture_output=True,
                timeout=5
            )
            # squashfs tools print version to stderr and may return 0 or 1
            # Check if output contains version info
            output = result.stdout.decode() + result.stderr.decode()
            return "version" in output.lower() and tool in output.lower()
        except FileNotFoundError:
            return False
        except subprocess.TimeoutExpired:
            return False
    
    def _check_overlayfs(self) -> bool:
        """Check if overlay filesystem is available."""
        # Check if overlay is supported by the kernel
        # Method 1: Check /proc/filesystems (most reliable)
        try:
            with open("/proc/filesystems", "r") as f:
                filesystems = f.read()
                if "overlay" in filesystems:
                    return True
        except (FileNotFoundError, PermissionError):
            pass
        
        # Method 2: Try modprobe (if available)
        try:
            result = subprocess.run(
                ["modprobe", "-n", "overlay"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        # Method 3: Check if overlay module is loaded
        try:
            result = subprocess.run(
                ["lsmod"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0 and b"overlay" in result.stdout:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        return False
    
    async def create(self, name: str, extra_metadata: Optional[Dict[str, Any]] = None, clone_images: dict | None = None) -> bool:
        """
        Create squashfs snapshot including data and configs.

        CRITICAL: Includes both data (cache/data/) and configs (cache/configs/)
        to preserve static_genesis_event and other genesis configuration.

        Args:
            name: Snapshot name
            extra_metadata: Optional dict to store in {name}.metadata (e.g. emission_hash)

        Returns:
            True if snapshot created successfully
        """
        if not self.has_mksquashfs:
            logger.error("squashfs_mksquashfs_not_available")
            return False
        
        logger.info("squashfs_create_start",
                   name=name,
                   compression=self.compression or "none")
        
        snapshot_file = self.snapshots_path / f"{name}.sqfs"
        
        # Remove existing snapshot if present
        if snapshot_file.exists():
            logger.debug("squashfs_overwriting_existing", name=name)
            snapshot_file.unlink()
        
        # Get source directories
        data_path = self.cache_path / "data"
        configs_path = self.cache_path / "configs"
        
        if not data_path.exists():
            logger.warning("squashfs_no_data_to_snapshot")
            return False
        
        # Create temporary exclude file for mksquashfs
        import tempfile
        exclude_file = Path(tempfile.mkstemp(suffix='.exclude', prefix='squashfs_')[1])
        
        try:
            # Write exclude patterns to file
            # Exclude run/ directories (contain Unix sockets, symlinks and PID files that are runtime-specific)
            # CRITICAL: Must exclude entire run/ directory to prevent Unix socket files from being included
            exclude_patterns = list(SNAPSHOT_EXCLUDE_PATTERNS)
            exclude_file.write_text('\n'.join(exclude_patterns))
            
            # Build mksquashfs command - pass source directories directly
            # mksquashfs handles symlinks correctly by itself
            cmd = ["mksquashfs"]
            
            # Add data directory
            cmd.append(str(data_path))
            
            # Add configs directory if it exists
            if configs_path.exists():
                logger.info("squashfs_snapshotting_configs",
                           note="Including configs to preserve static_genesis_event")
                cmd.append(str(configs_path))
            
            # Add destination file
            cmd.append(str(snapshot_file))
            
            # Add exclude file option
            cmd.extend(["-ef", str(exclude_file)])
            
            # Add compression
            if self.compression:
                cmd.extend(["-comp", self.compression])
            else:
                cmd.extend(["-noI", "-noD", "-noF", "-noX"])  # Disable all compression
            
            # Add other options for speed
            cmd.extend([
                "-no-progress",
                "-processors", "4",  # Use 4 processors for parallel compression
            ])
            
            # Run mksquashfs
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                logger.error("squashfs_create_failed",
                            name=name,
                            error=stderr.decode())
                return False
            
            # Create metadata (JSON sidecar next to .sqfs; include extra_metadata e.g. emission_hash)
            metadata = {
                "name": name,
                "type": "squashfs",
                "compression": self.compression or "none",
                "size_bytes": snapshot_file.stat().st_size,
                "includes_configs": configs_path.exists(),
            }
            if extra_metadata:
                metadata.update(extra_metadata)
            metadata_file = self.snapshots_path / f"{name}.metadata"
            metadata_file.write_text(json.dumps(metadata, indent=2))
            
            logger.info("squashfs_create_complete",
                       name=name,
                       size=snapshot_file.stat().st_size,
                       compression=self.compression or "none",
                       includes_configs=configs_path.exists())
            return True
            
        except Exception as e:
            logger.error("squashfs_create_error", name=name, error=str(e))
            if snapshot_file.exists():
                snapshot_file.unlink()
            return False
        finally:
            # Cleanup exclude file
            if exclude_file.exists():
                exclude_file.unlink()
    
    def _copytree_skip_sockets(self, src: Path, dst: Path, dirs_exist_ok: bool = False):
        """
        Copy directory tree skipping Unix socket files and other special files.
        
        Args:
            src: Source directory
            dst: Destination directory
            dirs_exist_ok: If True, allow destination to exist
        """
        if not src.exists():
            return
        
        if dst.exists() and not dirs_exist_ok:
            raise FileExistsError(f"Destination {dst} already exists")
        
        dst.mkdir(parents=True, exist_ok=True)
        
        for item in src.iterdir():
            src_path = src / item.name
            dst_path = dst / item.name
            
            try:
                # Check if it's a Unix socket file - try multiple methods
                is_socket = False
                try:
                    # Method 1: Use Path.is_socket() if available (Python 3.8+)
                    if hasattr(src_path, 'is_socket'):
                        is_socket = src_path.is_socket()
                    # Method 2: Check via stat()
                    if not is_socket and src_path.exists():
                        file_stat = src_path.stat()
                        is_socket = stat.S_ISSOCK(file_stat.st_mode)
                except (OSError, AttributeError):
                    # File might not exist or be inaccessible, skip check
                    pass
                
                if is_socket:
                    logger.debug("skipping_unix_socket_file",
                               path=str(src_path),
                               note="Unix sockets cannot be copied and will be recreated at runtime")
                    continue
                
                # Check for FIFO files (named pipes)
                try:
                    if src_path.exists():
                        file_stat = src_path.stat()
                        if stat.S_ISFIFO(file_stat.st_mode):
                            logger.debug("skipping_fifo_file",
                                       path=str(src_path))
                            continue
                except OSError:
                    pass
                
                # Copy directories recursively
                if src_path.is_dir():
                    self._copytree_skip_sockets(src_path, dst_path, dirs_exist_ok=True)
                # Copy regular files
                elif src_path.is_file():
                    shutil.copy2(src_path, dst_path)
                # Copy symlinks
                elif src_path.is_symlink():
                    link_target = src_path.readlink()
                    dst_path.symlink_to(link_target)
                else:
                    logger.debug("skipping_special_file",
                               path=str(src_path),
                               note="Unknown file type")
            except (OSError, shutil.Error) as e:
                # Skip files that can't be copied (sockets, devices, etc.)
                if hasattr(e, 'errno') and e.errno == 6:  # ENXIO - No such device or address (Unix sockets)
                    logger.debug("skipping_unix_socket_during_copy",
                               path=str(src_path),
                               error=str(e))
                    continue
                else:
                    logger.warning("copy_file_error",
                                 path=str(src_path),
                                 error=str(e))
                    # Continue with other files
    
    async def restore(self, name: str) -> bool:
        """
        Restore data and configs from squashfs snapshot.
        
        CRITICAL: Restores both data (cache/data/) and configs (cache/configs/)
        to restore static_genesis_event and other genesis configuration.
        
        Args:
            name: Snapshot name
            
        Returns:
            True if restore successful
        """
        if not self.has_unsquashfs:
            logger.error("squashfs_unsquashfs_not_available")
            return False
        
        logger.info("squashfs_restore_start", name=name)
        
        snapshot_file = self.snapshots_path / f"{name}.sqfs"
        
        if not snapshot_file.exists():
            logger.error("squashfs_snapshot_not_found", name=name)
            return False
        
        data_path = self.cache_path / "data"
        configs_path = self.cache_path / "configs"
        
        # Create temporary directory for extraction
        import tempfile
        import shutil
        temp_extract_dir = Path(tempfile.mkdtemp(prefix="squashfs_extract_"))
        
        try:
            # Extract squashfs to temp directory - need sudo as files are owned by root
            proc = await asyncio.create_subprocess_exec(
                "sudo", "unsquashfs",
                "-f",  # force overwrite
                "-no-xattrs",  # don't restore extended attributes
                "-d", str(temp_extract_dir),  # destination
                str(snapshot_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await proc.communicate()
            
            if proc.returncode != 0:
                logger.error("squashfs_restore_failed",
                            name=name,
                            error=stderr.decode())
                return False
            
            # Restore data directory
            data_snapshot_dir = temp_extract_dir / "data"
            if data_snapshot_dir.exists():
                # Clean existing data
                if data_path.exists():
                    logger.debug("squashfs_cleaning_existing_data")
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            "sudo", "rm", "-rf", str(data_path),
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
                        await proc.communicate()
                    except Exception:
                        await asyncio.to_thread(shutil.rmtree, data_path, ignore_errors=True)
                
                data_path.mkdir(parents=True, exist_ok=True)
                # Use custom copy function that skips Unix socket files
                await asyncio.to_thread(self._copytree_skip_sockets, data_snapshot_dir, data_path, dirs_exist_ok=True)
            else:
                # Legacy snapshot format - data directly in extract_dir
                logger.debug("squashfs_legacy_snapshot_format")
                if data_path.exists():
                    await asyncio.to_thread(shutil.rmtree, data_path, ignore_errors=True)
                data_path.mkdir(parents=True, exist_ok=True)
                # Use custom copy function that skips Unix socket files
                await asyncio.to_thread(self._copytree_skip_sockets, temp_extract_dir, data_path, dirs_exist_ok=True)
            
            # Restore configs directory if it exists in snapshot
            # CRITICAL: MUST restore configs from snapshot!
            # Snapshot contains configs with correct static_genesis_event
            # After restore, configs will be preserved unless explicitly regenerated
            configs_snapshot_dir = temp_extract_dir / "configs"
            if configs_snapshot_dir.exists():
                logger.info("squashfs_restoring_configs",
                           note="Restoring configs from snapshot to get static_genesis_event")
                
                # Clean existing configs first (only for nodes in snapshot)
                if configs_path.exists():
                    config_dirs = [d for d in configs_snapshot_dir.iterdir() 
                                  if d.is_dir() and not d.name.startswith('.')]
                    for config_dir in config_dirs:
                        target_config_dir = configs_path / config_dir.name
                        if target_config_dir.exists():
                            await asyncio.to_thread(shutil.rmtree, target_config_dir, ignore_errors=True)
                else:
                    configs_path.mkdir(parents=True, exist_ok=True)
                
                # Restore configs (use custom copy to skip any socket files)
                await asyncio.to_thread(self._copytree_skip_sockets, configs_snapshot_dir, configs_path, dirs_exist_ok=True)
                
                logger.info("squashfs_configs_restored",
                           note="Configs restored from snapshot with static_genesis_event")
            else:
                logger.debug("squashfs_no_configs_in_snapshot",
                           note="Legacy snapshot or configs not included")
            
            # Fix ownership to current user (files were extracted as root)
            import os
            uid = os.getuid()
            gid = os.getgid()
            
            for path in [data_path, configs_path]:
                if path.exists():
                    proc = await asyncio.create_subprocess_exec(
                        "sudo", "chown", "-R", f"{uid}:{gid}", str(path),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await proc.communicate()
            
            # Remove stale MDBX lock files — restored from snapshot they
            # reference PIDs that no longer exist and block new processes.
            if data_path.exists():
                proc = await asyncio.create_subprocess_exec(
                    "sudo", "find", str(data_path),
                    "-name", "mdbx.lck", "-delete",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()

            logger.info("squashfs_restore_complete", name=name)
            return True
            
        except Exception as e:
            logger.error("squashfs_restore_error", name=name, error=str(e))
            return False
        finally:
            # Cleanup temp directory
            if temp_extract_dir.exists():
                await asyncio.to_thread(shutil.rmtree, temp_extract_dir, ignore_errors=True)
    
    async def delete(self, name: str) -> bool:
        """
        Delete a squashfs snapshot.
        
        Args:
            name: Snapshot name
            
        Returns:
            True if deleted successfully
        """
        snapshot_file = self.snapshots_path / f"{name}.sqfs"
        metadata_file = self.snapshots_path / f"{name}.metadata"
        
        deleted = False
        
        if snapshot_file.exists():
            snapshot_file.unlink()
            deleted = True
        
        if metadata_file.exists():
            metadata_file.unlink()
        
        if deleted:
            logger.info("squashfs_snapshot_deleted", name=name)
        else:
            logger.debug("squashfs_snapshot_not_found", name=name)
        
        return True
    
    async def list(self) -> List[str]:
        """
        List available squashfs snapshots.
        
        Returns:
            List of snapshot names
        """
        if not self.snapshots_path.exists():
            return []
        
        snapshots = []
        for snapshot_file in self.snapshots_path.glob("*.sqfs"):
            snapshots.append(snapshot_file.stem)
        
        return sorted(snapshots)

    def load_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Load snapshot metadata from {name}.metadata (JSON sidecar next to .sqfs).
        Used by SnapshotManager.get_snapshot_metadata for emission_hash etc.
        """
        metadata_file = self.snapshots_path / f"{name}.metadata"
        if not metadata_file.exists():
            return None
        try:
            text = metadata_file.read_text().strip()
            if not text:
                return None
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                import ast
                return ast.literal_eval(text)
        except Exception as e:
            logger.debug("squashfs_load_metadata_failed", name=name, error=str(e))
            return None
    
    def exists(self, name: str) -> bool:
        return (self.snapshots_path / f"{name}.sqfs").exists()

    def get_info(self, name: str) -> Dict[str, Any]:
        """Get squashfs snapshot information."""
        snapshot_file = self.snapshots_path / f"{name}.sqfs"
        metadata_file = self.snapshots_path / f"{name}.metadata"
        
        info = {
            "name": name,
            "type": "squashfs",
            "path": str(snapshot_file),
            "exists": snapshot_file.exists(),
        }
        
        if snapshot_file.exists():
            info["size_bytes"] = snapshot_file.stat().st_size
            info["created"] = snapshot_file.stat().st_mtime
        
        # Read metadata if available (JSON or legacy repr)
        metadata = self.load_metadata(name)
        if metadata:
            info.update(metadata)
        
        return info

