"""
Base interface for snapshot implementations.

Defines the common interface that all snapshot modes must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any, List

from src.utils.logger import get_logger

logger = get_logger(__name__)

SNAPSHOT_EXCLUDE_PATTERNS = [
    "*/run/",
    "*/run/node_cli",
    "*/run/*.pid",
    "*/mdbx.lck",
]


class BaseSnapshot(ABC):
    """
    Abstract base class for snapshot implementations.
    
    All snapshot modes (recreate, filesystem, squashfs) inherit from this
    and implement the required methods.
    """
    
    def __init__(self, base_path: Path, config: Dict[str, Any], compose_manager=None):
        """
        Initialize snapshot handler.
        
        Args:
            base_path: Base path to stage-env directory
            config: Configuration dictionary
            compose_manager: Optional DockerComposeManager for container operations
        """
        self.base_path = base_path
        self.config = config
        self.compose_manager = compose_manager
        
        cache_dir = config.get('cache_dir', '../../cache')
        self.cache_path = (base_path / cache_dir).resolve()
        
        snapshots_dir = config.get('snapshots_dir', '../../cache/snapshots')
        self.snapshots_path = (base_path / snapshots_dir).resolve()
        self.snapshots_path.mkdir(parents=True, exist_ok=True)
        
        logger.debug("snapshot_handler_initialized",
                    type=self.__class__.__name__,
                    cache_path=str(self.cache_path),
                    snapshots_path=str(self.snapshots_path))
    
    @abstractmethod
    async def create(self, name: str, extra_metadata: Optional[Dict[str, Any]] = None, clone_images: dict | None = None) -> bool:
        """
        Create a snapshot.

        Args:
            name: Snapshot name
            extra_metadata: Optional dict to merge into snapshot metadata (e.g. emission_hash)
            clone_images: Optional mapping {source_service: [target_services]}

        Returns:
            True if successful
        """
        pass
    
    @abstractmethod
    async def restore(self, name: str) -> bool:
        """Restore from snapshot."""
        pass
    
    @abstractmethod
    async def delete(self, name: str) -> bool:
        """Delete a snapshot."""
        pass
    
    @abstractmethod
    async def list(self) -> List[str]:
        """List available snapshots."""
        pass

    @abstractmethod
    def exists(self, name: str) -> bool:
        """Check whether a named snapshot exists."""
        pass
    
    def get_info(self, name: str) -> Optional[Dict[str, Any]]:
        """Get snapshot information."""
        snapshot_path = self.snapshots_path / name
        if not snapshot_path.exists():
            return None
        
        return {
            "name": name,
            "path": str(snapshot_path),
            "exists": snapshot_path.exists(),
            "type": self.__class__.__name__,
        }
    
    def get_data_dirs(self) -> List[Path]:
        """Get list of data directories to snapshot."""
        data_path = self.cache_path / "data"
        if not data_path.exists():
            return []
        return [d for d in data_path.iterdir() if d.is_dir()]

    def get_config_dirs(self) -> List[Path]:
        """Get list of config directories to snapshot."""
        configs_path = self.cache_path / "configs"
        if not configs_path.exists():
            return []
        return [d for d in configs_path.iterdir() if d.is_dir()]
