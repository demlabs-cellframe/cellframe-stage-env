"""
Configuration checkers for genesis operations.
"""

from pathlib import Path
from typing import Optional, Tuple

from .base import BaseChecker
from ...utils.logger import get_logger
from ...config.manager import get_config_loader

logger = get_logger(__name__)


class ZerochainConfigChecker(BaseChecker):
    """
    Verify zerochain configuration and return config values.
    
    Checks:
    1. Zerochain config file exists
    2. [dag] section exists
    3. static_genesis_event parameter exists
    4. is_static_genesis_event parameter exists
    5. Base config file exists
    6. [general] section exists in base config
    7. seed_mode parameter exists in base config
    
    Usage:
        checker = ZerochainConfigChecker(base_path, node_id, network_name)
        result = await checker.verify_and_get()  # Returns (static_genesis_hash, is_static_genesis, seed_mode)
        # Or use verify() to just check without returning values
        await checker.verify()
    """
    
    def __init__(
        self,
        base_path: Path,
        node_id: int,
        network_name: str = "stagenet",
        config_path: Optional[Path] = None
    ):
        """
        Initialize zerochain config checker.
        
        Args:
            base_path: Base path to stage-env directory
            node_id: Node ID to check
            network_name: Network name (default: stagenet)
            config_path: Optional path to stage-env.cfg (for cache_dir resolution)
        """
        self.base_path = base_path
        self.node_id = node_id
        self.network_name = network_name
        self.config_path = config_path
        self._cached_result = None
    
    async def check(self) -> bool:
        """
        Check if zerochain config is valid.
        
        Returns:
            True if config is valid, False otherwise
        """
        try:
            await self.verify_and_get()
            return True
        except RuntimeError:
            return False
    
    async def verify_and_get(self) -> Tuple[Optional[str], bool, Optional[str]]:
        """
        Verify zerochain configuration and return config values.
        
        Returns:
            Tuple of (static_genesis_hash, is_static_genesis, seed_mode)
            Returns (None, False, None) if zerochain config doesn't exist
            
        Raises:
            RuntimeError: If config structure is invalid or required parameters are missing
        """
        if self._cached_result is not None:
            return self._cached_result
        
        # Get cache_dir from config (strictly from --config path, no fallback)
        from ...config.manager import get_config_loader
        config_loader = get_config_loader()
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', 'cache')
        cache_dir = (self.base_path / cache_dir_relative).resolve()
        
        # Build config paths strictly from base_path and cache_dir from config
        zerochain_config_path = cache_dir / "configs" / f"node{self.node_id}" / "network" / self.network_name / "zerochain.cfg"
        base_config_path = cache_dir / "configs" / f"node{self.node_id}" / "cellframe-node.cfg"
        
        static_genesis_hash = None
        is_static_genesis = False
        seed_mode = None
        
        if not zerochain_config_path.exists():
            logger.debug("zerochain_config_not_found",
                        path=str(zerochain_config_path),
                        note="Zerochain config does not exist - this is OK for initial genesis")
            self._cached_result = (None, False, None)
            return self._cached_result
        
        # Use centralized config manager
        config_loader = get_config_loader()
        config = config_loader.load_config_file(zerochain_config_path)
        
        # Verify [dag] section exists
        if 'dag' not in config:
            raise RuntimeError(
                f"CRITICAL: [dag] section not found in zerochain config at {zerochain_config_path}! "
                f"Cannot proceed without dag section."
            )
        
        # Verify static_genesis_event parameter exists
        if 'static_genesis_event' not in config['dag']:
            raise RuntimeError(
                f"CRITICAL: static_genesis_event not found in [dag] section at {zerochain_config_path}! "
                f"Cannot proceed without static_genesis_event."
            )
        static_genesis_hash = config['dag']['static_genesis_event'].strip()
        
        # Verify is_static_genesis_event parameter exists
        if 'is_static_genesis_event' not in config['dag']:
            raise RuntimeError(
                f"CRITICAL: is_static_genesis_event not found in [dag] section at {zerochain_config_path}! "
                f"Cannot proceed without is_static_genesis_event flag."
            )
        is_static_genesis = config['dag'].getboolean('is_static_genesis_event')
        
        # Check base config for seed_mode (path already set above from cache_dir)
        if not base_config_path.exists():
            raise RuntimeError(
                f"CRITICAL: Base config not found at {base_config_path}! "
                f"Cannot proceed without base config."
            )
        
        # Use centralized config manager
        config_loader = get_config_loader()
        base_config = config_loader.load_config_file(base_config_path)
        
        # Verify [general] section exists (seed_mode is in [general], not [main])
        if 'general' not in base_config:
            raise RuntimeError(
                f"CRITICAL: [general] section not found in base config at {base_config_path}! "
                f"Cannot proceed without general section."
            )
        
        # Verify seed_mode parameter exists
        if 'seed_mode' not in base_config['general']:
            raise RuntimeError(
                f"CRITICAL: seed_mode not found in [general] section at {base_config_path}! "
                f"Cannot proceed without seed_mode parameter."
            )
        seed_mode = base_config['general']['seed_mode'].strip()
        
        logger.info("zerochain_config_verified",
                   static_genesis_hash=static_genesis_hash[:16] if static_genesis_hash else "NOT SET",
                   is_static_genesis_event=is_static_genesis,
                   seed_mode=seed_mode,
                   node_id=self.node_id)
        
        self._cached_result = (static_genesis_hash, is_static_genesis, seed_mode)
        return self._cached_result


# Backward compatibility function
async def verify_zerochain_config(
    base_path: Path,
    node_id: int,
    network_name: str = "stagenet",
    config_path: Optional[Path] = None
) -> Tuple[Optional[str], bool, Optional[str]]:
    """
    Verify zerochain configuration and return config values.
    
    This is a convenience function that uses ZerochainConfigChecker.
    For new code, prefer using ZerochainConfigChecker directly.
    
    Args:
        base_path: Base path to stage-env directory
        node_id: Node ID to check
        network_name: Network name (default: stagenet)
        config_path: Optional path to stage-env.cfg (for cache_dir resolution)
        
    Returns:
        Tuple of (static_genesis_hash, is_static_genesis, seed_mode)
        Returns (None, False, None) if zerochain config doesn't exist
        
    Raises:
        RuntimeError: If config structure is invalid or required parameters are missing
    """
    checker = ZerochainConfigChecker(base_path, node_id, network_name, config_path)
    return await checker.verify_and_get()


