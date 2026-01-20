"""
Custom exceptions for SLC Web Interface.
Centralized exception hierarchy for better error handling and DRY principle.
"""

from typing import Any, Dict, Optional


class SLCWebError(Exception):
    """Base exception for all SLC Web Interface errors."""
    
    def __init__(
        self,
        message: str,
        code: str = "UNKNOWN_ERROR",
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Initialize base error.
        
        Args:
            message: Human-readable error message
            code: Machine-readable error code
            details: Additional error context
        """
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for API responses."""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details
        }


class ConfigurationError(SLCWebError):
    """Raised when configuration is invalid."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, code="CONFIGURATION_ERROR", details=details)


class SLCExecutionError(SLCWebError):
    """Raised when SLC command execution fails."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, code="SLC_EXECUTION_ERROR", details=details)


class SLCCommandNotAllowedError(SLCWebError):
    """Raised when attempting to execute non-whitelisted SLC command."""
    
    def __init__(self, command: str, allowed_commands: list[str]) -> None:
        super().__init__(
            f"Command '{command}' not in whitelist",
            code="COMMAND_NOT_ALLOWED",
            details={"command": command, "allowed_commands": allowed_commands}
        )


class ValidationError(SLCWebError):
    """Raised when input validation fails."""
    
    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        error_details = details or {}
        if field:
            error_details["field"] = field
        super().__init__(message, code="VALIDATION_ERROR", details=error_details)


class ResourceNotFoundError(SLCWebError):
    """Raised when requested resource doesn't exist."""
    
    def __init__(
        self,
        resource_type: str,
        resource_id: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            f"{resource_type} '{resource_id}' not found",
            code="RESOURCE_NOT_FOUND",
            details={"resource_type": resource_type, "resource_id": resource_id, **(details or {})}
        )


class CacheError(SLCWebError):
    """Raised when cache operations fail."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, code="CACHE_ERROR", details=details)


class FileWatcherError(SLCWebError):
    """Raised when file watcher encounters errors."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, code="FILE_WATCHER_ERROR", details=details)


class WebSocketError(SLCWebError):
    """Raised when WebSocket operations fail."""
    
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message, code="WEBSOCKET_ERROR", details=details)
