"""
Base models and mixins for DRY principle.
Reusable components for all Pydantic models.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, ConfigDict


class TimestampMixin(BaseModel):
    """Mixin for models with timestamps. DRY principle."""
    
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Creation timestamp (UTC)"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Last update timestamp (UTC)"
    )
    
    def touch(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.utcnow()


class IdentifierMixin(BaseModel):
    """Mixin for models with unique identifiers. DRY principle."""
    
    id: str = Field(..., description="Unique identifier", min_length=1)


class MetadataMixin(BaseModel):
    """Mixin for models with flexible metadata. DRY principle."""
    
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )


class BaseAPIModel(BaseModel):
    """
    Base model for all API models.
    Provides common configuration and utilities.
    """
    
    model_config = ConfigDict(
        # JSON schema generation
        json_schema_extra={
            "example": {}  # Override in subclasses
        },
        # Validation
        validate_assignment=True,
        use_enum_values=True,
        # Performance
        frozen=False,  # Allow mutation for business logic
        # Extras
        extra="forbid"  # Strict validation: no extra fields
    )
    
    def to_dict(self, exclude_none: bool = True) -> Dict[str, Any]:
        """
        Convert model to dictionary.
        
        Args:
            exclude_none: Exclude None values from output
        
        Returns:
            Dictionary representation
        """
        return self.model_dump(
            exclude_none=exclude_none,
            mode="python"
        )
    
    def to_json(self, exclude_none: bool = True) -> str:
        """
        Convert model to JSON string.
        
        Args:
            exclude_none: Exclude None values from output
        
        Returns:
            JSON string representation
        """
        return self.model_dump_json(
            exclude_none=exclude_none,
            indent=2
        )


class PaginationParams(BaseModel):
    """Reusable pagination parameters for API endpoints."""
    
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Items per page (max 100)"
    )
    
    @property
    def offset(self) -> int:
        """Calculate offset for database queries."""
        return (self.page - 1) * self.page_size
    
    @property
    def limit(self) -> int:
        """Get limit for database queries."""
        return self.page_size


class SortParams(BaseModel):
    """Reusable sorting parameters for API endpoints."""
    
    sort_by: Optional[str] = Field(
        default=None,
        description="Field to sort by"
    )
    sort_order: Optional[str] = Field(
        default="asc",
        pattern="^(asc|desc)$",
        description="Sort order: asc or desc"
    )
    
    @property
    def is_descending(self) -> bool:
        """Check if sort order is descending."""
        return self.sort_order == "desc"


class FilterParams(BaseModel):
    """Base class for filter parameters. Extend in specific endpoints."""
    
    search: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Search query (full-text search)"
    )
