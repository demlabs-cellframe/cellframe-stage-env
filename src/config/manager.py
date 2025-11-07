"""
Centralized configuration manager for stage-env.

Provides singleton access to ConfigLoader instance to avoid multiple reads
and ensure consistent configuration across all modules.
"""

from pathlib import Path
from typing import Optional

from .loader import ConfigLoader
from ..utils.logger import get_logger

logger = get_logger(__name__)

# Global singleton instance
_config_loader: Optional[ConfigLoader] = None
_config_path: Optional[Path] = None
_base_path: Optional[Path] = None


def initialize_config(base_path: Path, config_path: Optional[Path] = None) -> None:
    """
    Initialize global configuration manager.
    
    Should be called once at application startup (in stage_env.py callback).
    
    Args:
        base_path: Base path to stage-env directory
        config_path: Optional path to stage-env.cfg (overrides default location)
    """
    global _config_loader, _config_path, _base_path
    
    _base_path = base_path
    _config_path = config_path
    
    # Create ConfigLoader instance
    _config_loader = ConfigLoader(base_path, config_path)
    
    # Try to load config immediately to validate it exists
    try:
        _config_loader.load_stage_config()
        logger.debug("config_manager_initialized", 
                    base_path=str(base_path),
                    config_path=str(config_path) if config_path else None)
    except FileNotFoundError:
        # Config not found - will use defaults when needed
        logger.warning("config_not_found_at_init",
                     config_path=str(config_path) if config_path else str(base_path / "config" / "stage-env.cfg"),
                     note="Config will use defaults - specify --config option or create config file")


def get_config_loader() -> ConfigLoader:
    """
    Get global ConfigLoader instance.
    
    Returns:
        ConfigLoader instance (initialized with defaults if not explicitly initialized)
        
    Raises:
        RuntimeError: If ConfigLoader was never initialized
    """
    global _config_loader, _base_path, _config_path
    
    if _config_loader is None:
        if _base_path is None:
            raise RuntimeError(
                "ConfigLoader not initialized. Call initialize_config() first or "
                "ensure stage_env.py callback sets up configuration."
            )
        # Auto-initialize with stored values (fallback)
        logger.warning("config_loader_auto_initialized",
                      note="ConfigLoader was accessed before explicit initialization - using stored values")
        _config_loader = ConfigLoader(_base_path, _config_path)
    
    return _config_loader


def reset_config() -> None:
    """
    Reset global configuration (for testing or reinitialization).
    """
    global _config_loader, _config_path, _base_path
    _config_loader = None
    _config_path = None
    _base_path = None
    logger.debug("config_manager_reset")

