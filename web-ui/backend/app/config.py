"""
Configuration module for SLC Web Interface Backend.
Loads settings from environment variables with Pydantic validation.

Improvements:
- Uses centralized exceptions
- Better path validation
- DRY principle for path checks
"""

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import ConfigurationError


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Validates configuration on initialization (FAIL-FAST).
    """
    
    # Application
    app_name: str = "SLC Web Interface"
    app_version: str = "0.1.0"
    debug: bool = Field(default=False, description="Enable debug mode")
    
    # Server
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, ge=1, le=65535, description="Server port")
    reload: bool = Field(default=False, description="Auto-reload on code changes")
    workers: int = Field(default=1, ge=1, le=32, description="Number of worker processes")
    
    # CORS
    cors_origins: List[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"],
        description="Allowed CORS origins"
    )
    cors_allow_credentials: bool = True
    cors_allow_methods: List[str] = ["*"]
    cors_allow_headers: List[str] = ["*"]
    
    # SLC Integration
    slc_project_root: Path = Field(
        default=Path("/home/naeper/work/cellframe-node"),
        description="Path to SLC project root (where ./slc CLI is located)"
    )
    slc_cli_path: Path = Field(
        default=Path("/home/naeper/work/cellframe-node/slc"),
        description="Path to SLC CLI executable"
    )
    slc_context_dir: Path = Field(
        default=Path("/home/naeper/work/cellframe-node/.context"),
        description="Path to .context directory"
    )
    
    # Cache
    cache_enabled: bool = Field(default=True, description="Enable in-memory caching")
    cache_ttl_seconds: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="Cache TTL in seconds"
    )
    cache_max_size: int = Field(
        default=1000,
        ge=10,
        le=10000,
        description="Maximum cache entries"
    )
    
    # File Watcher
    file_watcher_enabled: bool = Field(default=True, description="Enable file watching")
    file_watcher_patterns: List[str] = Field(
        default=["*.json", "*.md"],
        description="File patterns to watch"
    )
    file_watcher_debounce_ms: int = Field(
        default=500,
        ge=100,
        le=5000,
        description="File watcher debounce in milliseconds"
    )
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_json: bool = Field(default=False, description="Output logs in JSON format")
    
    # WebSocket
    websocket_heartbeat_interval: int = Field(
        default=30,
        ge=10,
        le=300,
        description="WebSocket heartbeat interval in seconds"
    )
    websocket_max_connections: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum concurrent WebSocket connections"
    )
    
    # Security
    api_rate_limit_per_minute: int = Field(
        default=100,
        ge=10,
        le=10000,
        description="API rate limit per minute per IP"
    )
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        validate_assignment=True
    )
    
    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is valid."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(
                f"Invalid log level: {v}. Must be one of {valid_levels}"
            )
        return v_upper
    
    def _validate_path_exists(self, path: Path, name: str, must_be_file: bool = False) -> None:
        """
        Validate that path exists. DRY helper method.
        
        Args:
            path: Path to validate
            name: Human-readable name for error message
            must_be_file: If True, path must be a file
        
        Raises:
            ConfigurationError: If path doesn't exist or has wrong type
        """
        if not path.exists():
            raise ConfigurationError(
                f"{name} does not exist: {path}",
                details={
                    "path": str(path),
                    "name": name,
                    "env_var": self._get_env_var_name(name)
                }
            )
        
        if must_be_file and not path.is_file():
            raise ConfigurationError(
                f"{name} is not a file: {path}",
                details={
                    "path": str(path),
                    "name": name
                }
            )
        
        if not must_be_file and not path.is_dir():
            raise ConfigurationError(
                f"{name} is not a directory: {path}",
                details={
                    "path": str(path),
                    "name": name
                }
            )
    
    def _get_env_var_name(self, setting_name: str) -> str:
        """Get environment variable name for setting. DRY helper."""
        return setting_name.upper().replace(" ", "_")
    
    def validate_paths(self) -> None:
        """
        Validate that all required paths exist. FAIL-FAST.
        
        Raises:
            ConfigurationError: If any path validation fails
        """
        # Validate directories
        self._validate_path_exists(
            self.slc_project_root,
            "SLC project root",
            must_be_file=False
        )
        
        self._validate_path_exists(
            self.slc_context_dir,
            "SLC .context directory",
            must_be_file=False
        )
        
        # Validate files
        self._validate_path_exists(
            self.slc_cli_path,
            "SLC CLI executable",
            must_be_file=True
        )
        
        # Check if CLI is executable
        if not self.slc_cli_path.stat().st_mode & 0o111:
            raise ConfigurationError(
                f"SLC CLI is not executable: {self.slc_cli_path}",
                details={
                    "path": str(self.slc_cli_path),
                    "hint": "Run: chmod +x " + str(self.slc_cli_path)
                }
            )
    
    def validate_all(self) -> None:
        """
        Validate all settings. FAIL-FAST on any error.
        Call this after loading settings.
        """
        self.validate_paths()
        
        # Additional validation can be added here
        if self.workers > 1 and self.reload:
            raise ConfigurationError(
                "Cannot use reload mode with multiple workers",
                details={
                    "workers": self.workers,
                    "reload": self.reload,
                    "hint": "Set workers=1 for development with reload"
                }
            )


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Validates settings on first access (FAIL-FAST).
    
    Returns:
        Validated Settings instance
    
    Raises:
        ConfigurationError: If settings validation fails
    """
    settings = Settings()
    settings.validate_all()
    return settings


# Convenience function for getting specific settings
def get_slc_config() -> tuple[Path, Path, Path]:
    """
    Get SLC-related configuration.
    Convenience function for common use case (DRY).
    
    Returns:
        Tuple of (cli_path, project_root, context_dir)
    """
    settings = get_settings()
    return (
        settings.slc_cli_path,
        settings.slc_project_root,
        settings.slc_context_dir
    )
