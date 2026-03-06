"""
Snapshot Manager - orchestrates different snapshot modes.

Backend is selected automatically at startup:
  squashfs  (mksquashfs + unsquashfs available)  — fastest
  filesystem (rsync available)                    — fallback
  recreate  (always available)                    — baseline
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.utils.logger import get_logger
from .base import BaseSnapshot
from .recreate import RecreateSnapshot
from .filesystem import FilesystemSnapshot
from .squashfs import SquashfsSnapshot

logger = get_logger(__name__)


class SnapshotMode(Enum):
    """Available snapshot isolation modes."""
    DISABLED = "disabled"
    RECREATE = "recreate"
    FILESYSTEM = "filesystem"
    SQUASHFS = "squashfs"


def _tool_available(name: str) -> bool:
    try:
        r = subprocess.run(
            [name, "-version"] if name in ("mksquashfs", "unsquashfs") else [name, "--version"],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0 or r.stdout or r.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def detect_best_mode() -> SnapshotMode:
    """Probe the host and return the best available snapshot backend."""
    if _tool_available("mksquashfs") and _tool_available("unsquashfs"):
        return SnapshotMode.SQUASHFS
    if _tool_available("rsync"):
        return SnapshotMode.FILESYSTEM
    return SnapshotMode.RECREATE


class SnapshotManager:
    """
    Manager for test environment snapshots.

    Provides fast environment restoration via different snapshot strategies.
    The backend is chosen automatically unless explicitly disabled.
    """
    
    def __init__(
        self,
        base_path: Path,
        config: Optional[Dict[str, Any]] = None,
        compose_manager=None,
        *,
        mode: SnapshotMode | None = None,
    ):
        self.base_path = base_path
        self.config = config or {}
        self.compose_manager = compose_manager

        if mode is not None:
            self.mode = mode
        else:
            self.mode = detect_best_mode()
        
        self.snapshot: Optional[BaseSnapshot] = None
        if self.mode != SnapshotMode.DISABLED:
            self._initialize_handler()
        
        logger.info("snapshot_manager_initialized",
                   mode=self.mode.value,
                   base_path=str(base_path),
                   has_compose_manager=compose_manager is not None)
    
    def _initialize_handler(self):
        if self.mode == SnapshotMode.RECREATE:
            self.snapshot = RecreateSnapshot(self.base_path, self.config)
        elif self.mode == SnapshotMode.FILESYSTEM:
            self.snapshot = FilesystemSnapshot(
                self.base_path, self.config,
                compose_manager=self.compose_manager,
            )
        elif self.mode == SnapshotMode.SQUASHFS:
            self.snapshot = SquashfsSnapshot(self.base_path, self.config)
        else:
            raise ValueError(f"Unknown snapshot mode: {self.mode}")

    # ------------------------------------------------------------------
    # Image metadata persistence (for clone_images across runs)
    # ------------------------------------------------------------------

    def _save_image_metadata(self, name: str, images: Dict[str, str]) -> None:
        meta_file = self.snapshot.snapshots_path / f"{name}.images.json"
        meta_file.write_text(json.dumps(images, indent=2))
        logger.debug("image_metadata_saved", name=name, file=str(meta_file))

    def _load_image_metadata(self, name: str) -> Dict[str, str]:
        meta_file = self.snapshot.snapshots_path / f"{name}.images.json"
        if not meta_file.exists():
            return {}
        try:
            return json.loads(meta_file.read_text())
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("image_metadata_load_failed", name=name, error=str(exc))
            return {}

    def _commit_and_clone(
        self, name: str, clone_images: dict,
    ) -> dict[str, str]:
        """Docker-commit source containers and map clones (mode-agnostic)."""
        images: dict[str, str] = {}
        for source in clone_images:
            container_name = f"cellframe-stage-{source}"
            tag = f"prototype-{source}"
            try:
                import docker
                client = docker.from_env()
                ctr = client.containers.get(container_name)
                ctr.commit(repository=tag, tag="latest")
                images[source] = f"{tag}:latest"
                logger.info("manager_docker_committed",
                           service=source, image=f"{tag}:latest")
            except Exception as e:
                logger.warning("manager_docker_commit_failed",
                              service=source, error=str(e))
                continue

        result = dict(images)
        for source, targets in clone_images.items():
            src_tag = images.get(source)
            if not src_tag:
                continue
            if isinstance(targets, str):
                targets = [targets]
            for target in targets:
                if target != source:
                    result[target] = src_tag
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    
    async def create_snapshot(
        self, name: str = "clean_state",
        clone_images: dict | None = None,
    ) -> bool:
        if self.mode == SnapshotMode.DISABLED:
            logger.debug("snapshot_disabled_create_skipped")
            return True
        
        logger.info("creating_snapshot", name=name, mode=self.mode.value)
        
        try:
            result = await self.snapshot.create(name, clone_images=clone_images)
            if not result:
                logger.error("snapshot_creation_failed", name=name)
                return False

            if clone_images and self.compose_manager:
                committed = self._commit_and_clone(name, clone_images)
                if committed:
                    self.compose_manager.set_service_images(committed)
                    self._save_image_metadata(name, committed)
                    logger.info("manager_clone_images_applied",
                               count=len(committed))

            logger.info("snapshot_created_successfully", name=name)
            return True
        except Exception as e:
            logger.error("snapshot_creation_error", name=name, error=str(e))
            return False
    
    async def restore_snapshot(self, name: str = "clean_state") -> bool:
        if self.mode == SnapshotMode.DISABLED:
            logger.debug("snapshot_disabled_restore_skipped")
            return True
        
        logger.info("restoring_snapshot", name=name, mode=self.mode.value)
        
        try:
            result = await self.snapshot.restore(name)
            if not result:
                logger.error("snapshot_restore_failed", name=name)
                return False

            committed = self._load_image_metadata(name)
            if committed and self.compose_manager:
                self.compose_manager.set_service_images(committed)
                logger.info("snapshot_images_restored",
                           count=len(committed),
                           services=list(committed.keys()))

            logger.info("snapshot_restored_successfully", name=name)
            return True
        except Exception as e:
            logger.error("snapshot_restore_error", name=name, error=str(e))
            return False
    
    async def delete_snapshot(self, name: str) -> bool:
        if self.mode == SnapshotMode.DISABLED:
            return True
        logger.info("deleting_snapshot", name=name)
        try:
            result = await self.snapshot.delete(name)
            if result:
                logger.info("snapshot_deleted_successfully", name=name)
            else:
                logger.error("snapshot_deletion_failed", name=name)
            return result
        except Exception as e:
            logger.error("snapshot_deletion_error", name=name, error=str(e))
            return False
    
    async def list_snapshots(self) -> List[str]:
        if self.mode == SnapshotMode.DISABLED:
            return []
        try:
            return await self.snapshot.list()
        except Exception as e:
            logger.error("snapshot_list_error", error=str(e))
            return []
    
    async def cleanup_old_snapshots(self, keep_count: int = 5) -> int:
        if self.mode == SnapshotMode.DISABLED:
            return 0
        try:
            snapshots = await self.list_snapshots()
            if len(snapshots) <= keep_count:
                return 0
            snapshots.sort()
            to_delete = snapshots[:-keep_count]
            deleted = 0
            for name in to_delete:
                if await self.delete_snapshot(name):
                    deleted += 1
            logger.info("old_snapshots_cleaned", deleted=deleted, kept=keep_count)
            return deleted
        except Exception as e:
            logger.error("snapshot_cleanup_error", error=str(e))
            return 0
    
    def get_snapshot_info(self, name: str) -> Optional[Dict[str, Any]]:
        if self.mode == SnapshotMode.DISABLED:
            return None
        try:
            return self.snapshot.get_info(name)
        except Exception as e:
            logger.error("snapshot_info_error", name=name, error=str(e))
            return None
