"""
Hybrid snapshot mode - filesystem rsync + Docker commit.

Creates snapshots by:
1. rsync'ing bind-mounted data/config directories (filesystem layer)
2. docker commit'ing each container (captures dpkg state, writable layer)

On restore:
1. rsync data/configs back from snapshot
2. Update docker-compose to use committed images (skips dpkg reinstall)
3. Caller is responsible for stopping containers before and starting after
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import subprocess

from src.utils.logger import get_logger
from .base import BaseSnapshot, SNAPSHOT_EXCLUDE_PATTERNS

logger = get_logger(__name__)


class FilesystemSnapshot(BaseSnapshot):
    """
    Hybrid filesystem + Docker commit snapshot mode.
    
    Filesystem layer: rsync cache/data + cache/configs directories.
    Docker layer: commit each container to capture installed packages,
    dpkg database, and any state outside bind mounts.
    
    On restore, committed images are used via docker-compose so containers
    come up with dpkg state intact, eliminating redundant package installs.
    """
    
    def __init__(self, base_path: Path, config: Dict[str, Any], compose_manager=None):
        """
        Initialize hybrid snapshot handler.
        
        Args:
            base_path: Base path to stage-env directory
            config: Configuration dictionary
            compose_manager: Optional DockerComposeManager for container operations
            
        Raises:
            RuntimeError: If rsync is not available (fail-fast)
        """
        super().__init__(base_path, config, compose_manager)
        
        if not self._check_rsync():
            raise RuntimeError(
                "Filesystem mode selected but rsync is not installed. "
                "Install rsync: sudo apt install rsync"
            )
        
        self._docker = getattr(self.compose_manager, 'client', None) if self.compose_manager else None
        if not self._docker:
            logger.warning("docker_sdk_not_available",
                          note="Docker commit will be skipped — no compose_manager or client")
        
        logger.info("filesystem_mode_initialized",
                   rsync_available=True,
                   docker_available=self._docker is not None,
                   snapshots_dir=str(self.snapshots_path))
    
    def _check_rsync(self) -> bool:
        """Check if rsync is available on the system."""
        try:
            result = subprocess.run(
                ["rsync", "--version"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False
        except subprocess.TimeoutExpired:
            return False
    
    async def create(self, name: str, clone_images: dict | None = None) -> bool:
        """
        Create hybrid snapshot: rsync data/configs + docker commit containers.
        
        Args:
            name: Snapshot name
            clone_images: Optional mapping {source_service: [target_services]}.
                          The prototype's committed image is reused for all
                          target services, avoiding redundant package installs.
            
        Returns:
            True if snapshot created successfully
        """
        logger.info("filesystem_create_start", name=name)
        
        snapshot_dir = self.snapshots_path / name
        
        if snapshot_dir.exists():
            logger.debug("filesystem_overwriting_existing", name=name)
            await self.delete(name)
        
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        data_dirs = self.get_data_dirs()
        config_dirs = self.get_config_dirs()
        
        if not data_dirs:
            logger.warning("filesystem_no_data_to_snapshot")
            return False
        
        try:
            data_snapshot_dir = snapshot_dir / "data"
            data_snapshot_dir.mkdir(exist_ok=True)
            
            for node_dir in data_dirs:
                target_dir = data_snapshot_dir / node_dir.name
                await self._rsync_copy(node_dir, target_dir)
            
            if config_dirs:
                config_snapshot_dir = snapshot_dir / "configs"
                config_snapshot_dir.mkdir(exist_ok=True)
                
                for config_dir in config_dirs:
                    target_dir = config_snapshot_dir / config_dir.name
                    await self._rsync_copy(config_dir, target_dir)
            
            committed_images = await self._commit_containers(name)

            if clone_images:
                committed_images = self._apply_clone_images(
                    committed_images, clone_images,
                )

            metadata = self._create_metadata(name, data_dirs, config_dirs, committed_images)
            metadata_file = snapshot_dir / ".snapshot_metadata"
            metadata_file.write_text(json.dumps(metadata, indent=2))
            
            logger.info("filesystem_create_complete",
                       name=name,
                       nodes=len(data_dirs),
                       configs=len(config_dirs) if config_dirs else 0,
                       images=len(committed_images),
                       size=self._get_dir_size(snapshot_dir))
            return True
            
        except Exception as e:
            logger.error("filesystem_create_failed", name=name, error=str(e))
            if snapshot_dir.exists():
                await asyncio.to_thread(shutil.rmtree, snapshot_dir, ignore_errors=True)
            return False
    
    async def restore(self, name: str) -> bool:
        """
        Restore from hybrid snapshot: rsync data/configs + set committed images.
        
        IMPORTANT: Caller must stop containers before calling this method
        and start them after. This method only handles data operations and
        compose file updates.
        
        Args:
            name: Snapshot name
            
        Returns:
            True if restore successful
        """
        logger.info("filesystem_restore_start", name=name)
        
        snapshot_dir = self.snapshots_path / name
        
        if not snapshot_dir.exists():
            logger.error("filesystem_snapshot_not_found", name=name)
            return False
        
        data_path = self.cache_path / "data"
        configs_path = self.cache_path / "configs"
        
        try:
            data_snapshot_dir = snapshot_dir / "data"
            if data_snapshot_dir.exists():
                if data_path.exists():
                    await self._docker_cleanup(data_path)
                
                data_path.mkdir(parents=True, exist_ok=True)
                
                node_dirs = [d for d in data_snapshot_dir.iterdir() 
                            if d.is_dir() and not d.name.startswith('.')]
                
                for node_dir in node_dirs:
                    target_dir = data_path / node_dir.name
                    await self._rsync_copy(node_dir, target_dir)
            else:
                logger.debug("filesystem_legacy_snapshot_format")
                if data_path.exists():
                    await self._docker_cleanup(data_path)
                
                data_path.mkdir(parents=True, exist_ok=True)
                
                node_dirs = [d for d in snapshot_dir.iterdir() 
                            if d.is_dir() and not d.name.startswith('.')]
                
                for node_dir in node_dirs:
                    target_dir = data_path / node_dir.name
                    await self._rsync_copy(node_dir, target_dir)
            
            config_snapshot_dir = snapshot_dir / "configs"
            if config_snapshot_dir.exists():
                snapshot_config_names = {
                    d.name for d in config_snapshot_dir.iterdir()
                    if d.is_dir() and not d.name.startswith('.')
                }

                if configs_path.exists():
                    removed_extra = 0
                    for existing_dir in list(configs_path.iterdir()):
                        if existing_dir.is_dir() and not existing_dir.name.startswith('.'):
                            if existing_dir.name not in snapshot_config_names and existing_dir.name != "shared":
                                await asyncio.to_thread(shutil.rmtree, existing_dir, ignore_errors=True)
                                removed_extra += 1
                    if removed_extra:
                        logger.info("filesystem_removed_extra_configs", count=removed_extra)
                else:
                    configs_path.mkdir(parents=True, exist_ok=True)

                config_dirs = [d for d in config_snapshot_dir.iterdir()
                              if d.is_dir() and not d.name.startswith('.')]

                for config_dir in config_dirs:
                    target_dir = configs_path / config_dir.name
                    await self._rsync_copy(config_dir, target_dir)

                logger.info("filesystem_configs_restored", nodes=len(config_dirs))
            
            metadata = self._load_metadata(name)
            committed_images = metadata.get("images", {}) if metadata else {}
            
            if committed_images and self.compose_manager:
                logger.info("filesystem_applying_committed_images",
                           count=len(committed_images))
                self.compose_manager.set_service_images(committed_images)
            elif committed_images:
                logger.warning("filesystem_committed_images_skipped",
                             reason="no compose_manager available")
            
            logger.info("filesystem_restore_complete",
                       name=name,
                       nodes=len(node_dirs),
                       images_applied=len(committed_images))
            return True
            
        except Exception as e:
            logger.error("filesystem_restore_failed", name=name, error=str(e))
            return False
    
    async def delete(self, name: str) -> bool:
        """
        Delete snapshot: remove directory and committed Docker images.
        
        Args:
            name: Snapshot name
            
        Returns:
            True if deleted successfully
        """
        snapshot_dir = self.snapshots_path / name
        
        if not snapshot_dir.exists():
            logger.debug("filesystem_snapshot_not_found", name=name)
            return True
        
        try:
            metadata = self._load_metadata(name)
            if metadata and metadata.get("images"):
                await self._remove_committed_images(metadata["images"])
            
            await asyncio.to_thread(shutil.rmtree, snapshot_dir)
            logger.info("filesystem_snapshot_deleted", name=name)
            return True
        except Exception as e:
            logger.error("filesystem_delete_failed", name=name, error=str(e))
            return False
    
    async def list(self) -> List[str]:
        """
        List available snapshots.
        
        Returns:
            List of snapshot names
        """
        if not self.snapshots_path.exists():
            return []
        
        snapshots = []
        for snapshot_dir in self.snapshots_path.iterdir():
            if snapshot_dir.is_dir() and not snapshot_dir.name.startswith('.'):
                snapshots.append(snapshot_dir.name)
        
        return sorted(snapshots)
    
    async def _docker_cleanup(self, path: Path):
        """
        Clean directory using Docker to handle root-owned files.
        
        Docker containers create files as root, which cannot be removed
        by regular user. This uses alpine container to remove them.
        
        Args:
            path: Directory to clean
        """
        try:
            # Use Docker to remove root-owned files
            proc = await asyncio.create_subprocess_exec(
                "docker", "run", "--rm",
                "-v", f"{path.parent}:/cleanup_target",
                "alpine", "sh", "-c",
                f"rm -rf /cleanup_target/{path.name}/* 2>/dev/null; "
                f"rm -rf /cleanup_target/{path.name} 2>/dev/null || true",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            logger.debug("docker_cleanup_complete", path=str(path))
        except Exception as e:
            logger.warning("docker_cleanup_failed_trying_rmtree", 
                          path=str(path), error=str(e))
            # Fallback to shutil.rmtree
            await asyncio.to_thread(shutil.rmtree, path, ignore_errors=True)

    async def _rsync_copy(self, source: Path, target: Path):
        """
        Copy directory using rsync.
        
        Args:
            source: Source directory
            target: Target directory
        """
        # Ensure target parent exists
        target.parent.mkdir(parents=True, exist_ok=True)
        
        # Run rsync
        # NOTE: Using -rlptD instead of -a to avoid owner/group preservation issues
        # Docker creates files as root, and rsync -a tries to preserve owner/group
        # which fails with "Operation not permitted" when running as regular user.
        # -r: recursive
        # -l: copy symlinks as symlinks
        # -p: preserve permissions
        # -t: preserve modification times
        # -D: preserve device files and special files
        # --no-owner --no-group: explicitly skip owner/group (redundant but clear)
        proc = await asyncio.create_subprocess_exec(
            "rsync",
            "-rlptD",  # archive mode WITHOUT owner/group
            "--no-owner",
            "--no-group",
            "--delete",
            "--exclude", "asan.*",
            *[arg for pat in SNAPSHOT_EXCLUDE_PATTERNS
              for arg in ("--exclude", pat)],
            str(source) + "/",  # trailing slash important!
            str(target) + "/",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            raise RuntimeError(f"rsync failed: {stderr.decode()}")
    
    def _apply_clone_images(
        self,
        committed: Dict[str, str],
        clone_images: dict,
    ) -> Dict[str, str]:
        """Replicate a prototype's committed image tag to target services.

        Args:
            committed: Current {service: image_tag} from docker commit.
            clone_images: {source_service: [target1, target2, ...]}.

        Returns:
            Extended committed dict with cloned entries.
        """
        result = dict(committed)
        for source, targets in clone_images.items():
            src_tag = committed.get(source)
            if not src_tag:
                logger.warning("clone_images_source_not_committed",
                               source=source,
                               available=list(committed.keys()))
                continue
            if isinstance(targets, str):
                targets = [targets]
            for target in targets:
                if target != source:
                    result[target] = src_tag
            logger.info("clone_images_applied",
                        source=source,
                        cloned_to=len([t for t in targets if t != source]))
        return result

    async def _commit_containers(self, name: str) -> Dict[str, str]:
        """
        Docker-commit each project container, capturing writable layer
        (installed packages, dpkg database, files outside bind mounts).
        
        Args:
            name: Snapshot name (used in image tag)
            
        Returns:
            Dict mapping service name to committed image tag
        """
        if not self._docker or not self.compose_manager:
            logger.debug("docker_commit_skipped",
                        has_docker=self._docker is not None,
                        has_compose=self.compose_manager is not None)
            return {}
        
        images: Dict[str, str] = {}
        
        try:
            containers = self.compose_manager.ps()
        except Exception as e:
            logger.warning("docker_commit_list_failed", error=str(e))
            return {}
        
        for container in containers:
            service = container.labels.get("com.docker.compose.service")
            if not service:
                continue
            
            container.reload()
            if container.status not in ("running", "exited"):
                logger.debug("docker_commit_skip_container",
                           service=service, status=container.status)
                continue
            
            tag = f"snapshot-{name}-{service}"
            try:
                container.commit(repository=tag)
                images[service] = tag
                logger.debug("docker_committed", service=service, tag=tag)
            except Exception as e:
                logger.warning("docker_commit_failed",
                             service=service, error=str(e))
        
        if images:
            logger.info("docker_commit_complete",
                       count=len(images),
                       services=list(images.keys()))
        
        return images
    
    async def _remove_committed_images(self, images: Dict[str, str]) -> None:
        """Remove committed Docker images for a snapshot."""
        if not self._docker:
            return
        
        for service, tag in images.items():
            try:
                self._docker.images.remove(tag, force=True)
                logger.debug("docker_image_removed", service=service, tag=tag)
            except Exception as e:
                logger.debug("docker_image_remove_skipped",
                           service=service, tag=tag, error=str(e))
    
    def _load_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """Load snapshot metadata from JSON file."""
        metadata_file = self.snapshots_path / name / ".snapshot_metadata"
        if not metadata_file.exists():
            return None
        
        text = metadata_file.read_text().strip()
        if not text:
            return None
        
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            try:
                return eval(text)
            except Exception:
                logger.warning("metadata_parse_failed", name=name)
                return None
    
    def _create_metadata(
        self,
        name: str,
        data_dirs: list[Path],
        config_dirs: list[Path] = None,
        images: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Create metadata dict for snapshot."""
        metadata: Dict[str, Any] = {
            "name": name,
            "type": "hybrid" if images else "filesystem",
            "nodes": [d.name for d in data_dirs],
            "created": time.time(),
        }
        
        if config_dirs:
            metadata["configs"] = [d.name for d in config_dirs]
        
        if images:
            metadata["images"] = images
        
        return metadata
    
    def _get_dir_size(self, path: Path) -> int:
        """Get total size of directory in bytes."""
        total = 0
        try:
            for entry in path.rglob('*'):
                if entry.is_file():
                    total += entry.stat().st_size
        except Exception:
            pass
        return total
    
    def exists(self, name: str) -> bool:
        return (self.snapshots_path / name).is_dir()

    def get_info(self, name: str) -> Dict[str, Any]:
        """Get snapshot information."""
        snapshot_dir = self.snapshots_path / name
        
        info = {
            "name": name,
            "type": "filesystem",
            "path": str(snapshot_dir),
            "exists": snapshot_dir.exists(),
        }
        
        if snapshot_dir.exists():
            info["size_bytes"] = self._get_dir_size(snapshot_dir)
            info["created"] = snapshot_dir.stat().st_mtime
            
            metadata = self._load_metadata(name)
            if metadata:
                info.update(metadata)
        
        return info

