"""
Standard API response models with DRY principle.
Reusable response wrappers for consistent API.
"""

from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import Field

from app.models.base import BaseAPIModel

T = TypeVar("T")


class ErrorDetail(BaseAPIModel):
    """Error detail information. Standardized error format."""
    
    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message")
    field: Optional[str] = Field(default=None, description="Field that caused error (if applicable)")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional error context")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid input data",
                "field": "title",
                "details": {"min_length": 1}
            }
        }
    }


class ErrorResponse(BaseAPIModel):
    """
    Standard error response.
    Used for all API errors for consistency.
    """
    
    success: bool = Field(default=False, frozen=True)
    error: ErrorDetail
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid input data",
                    "field": "title"
                }
            }
        }
    }
    
    @classmethod
    def from_exception(cls, exc: Exception, code: str = "INTERNAL_ERROR") -> "ErrorResponse":
        """
        Create error response from exception.
        Factory method for DRY.
        """
        # Check if it's our custom exception with to_dict method
        if hasattr(exc, "to_dict"):
            error_dict = exc.to_dict()  # type: ignore
            return cls(error=ErrorDetail(**error_dict))
        
        # Generic exception
        return cls(
            error=ErrorDetail(
                code=code,
                message=str(exc)
            )
        )


class SuccessResponse(BaseAPIModel, Generic[T]):
    """
    Generic success response.
    Wraps any data type with success status.
    """
    
    success: bool = Field(default=True, frozen=True)
    data: T
    message: Optional[str] = Field(default=None, description="Optional success message")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "data": {"key": "value"},
                "message": "Operation completed successfully"
            }
        }
    }
    
    @classmethod
    def create(cls, data: T, message: Optional[str] = None) -> "SuccessResponse[T]":
        """
        Create success response.
        Factory method for convenience.
        """
        return cls(data=data, message=message)


class PaginatedResponse(BaseAPIModel, Generic[T]):
    """
    Paginated response with metadata.
    Reusable for any paginated endpoint.
    """
    
    success: bool = Field(default=True, frozen=True)
    data: List[T]
    pagination: "PaginationMetadata"
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "data": [{"id": 1}, {"id": 2}],
                "pagination": {
                    "total": 100,
                    "page": 1,
                    "page_size": 20,
                    "total_pages": 5,
                    "has_next": True,
                    "has_prev": False
                }
            }
        }
    }
    
    @classmethod
    def create(
        cls,
        data: List[T],
        total: int,
        page: int,
        page_size: int
    ) -> "PaginatedResponse[T]":
        """
        Create paginated response with calculated metadata.
        Factory method that encapsulates pagination logic.
        """
        total_pages = (total + page_size - 1) // page_size  # Ceiling division
        
        pagination = PaginationMetadata(
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1
        )
        
        return cls(data=data, pagination=pagination)


class PaginationMetadata(BaseAPIModel):
    """Pagination metadata. Reusable component."""
    
    total: int = Field(..., ge=0, description="Total number of items")
    page: int = Field(..., ge=1, description="Current page number")
    page_size: int = Field(..., ge=1, le=100, description="Items per page")
    total_pages: int = Field(..., ge=0, description="Total number of pages")
    has_next: bool = Field(..., description="Has next page")
    has_prev: bool = Field(..., description="Has previous page")


class HealthCheckResponse(BaseAPIModel):
    """
    Health check response.
    Used for /health endpoint.
    """
    
    status: str = Field(default="healthy", description="Service health status")
    version: str = Field(..., description="Application version")
    uptime_seconds: float = Field(..., ge=0.0, description="Service uptime in seconds")
    slc_available: bool = Field(..., description="SLC CLI availability")
    checks: Dict[str, "HealthCheckItem"] = Field(
        default_factory=dict,
        description="Detailed health checks"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "healthy",
                "version": "0.1.0",
                "uptime_seconds": 1234.56,
                "slc_available": True,
                "checks": {
                    "database": {"status": "healthy", "latency_ms": 5.2},
                    "cache": {"status": "healthy", "latency_ms": 1.1}
                }
            }
        }
    }


class HealthCheckItem(BaseAPIModel):
    """Individual health check item."""
    
    status: str = Field(..., description="Check status (healthy/unhealthy/degraded)")
    latency_ms: Optional[float] = Field(default=None, ge=0.0, description="Check latency in milliseconds")
    message: Optional[str] = Field(default=None, description="Additional status message")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional details")


class CommandExecutionResponse(BaseAPIModel):
    """
    Response for CLI command execution.
    Specialized response for SLC commands.
    """
    
    success: bool = Field(..., description="Command execution success")
    command: str = Field(..., description="Executed command")
    exit_code: int = Field(..., description="Command exit code")
    output: Optional[str] = Field(default=None, description="Command output (stdout)")
    error: Optional[str] = Field(default=None, description="Command error (stderr)")
    parsed_data: Optional[Dict[str, Any]] = Field(default=None, description="Parsed JSON output")
    execution_time_ms: Optional[float] = Field(default=None, ge=0.0, description="Execution time in milliseconds")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "command": "./slc list",
                "exit_code": 0,
                "output": "...",
                "parsed_data": {"tasks": []},
                "execution_time_ms": 123.45
            }
        }
    }


# Helper functions for creating responses (DRY)

def success_response(data: T, message: Optional[str] = None) -> SuccessResponse[T]:
    """Create success response. Convenience function."""
    return SuccessResponse.create(data=data, message=message)


def error_response(
    code: str,
    message: str,
    field: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
) -> ErrorResponse:
    """Create error response. Convenience function."""
    return ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            field=field,
            details=details
        )
    )


def paginated_response(
    data: List[T],
    total: int,
    page: int,
    page_size: int
) -> PaginatedResponse[T]:
    """Create paginated response. Convenience function."""
    return PaginatedResponse.create(
        data=data,
        total=total,
        page=page,
        page_size=page_size
    )
