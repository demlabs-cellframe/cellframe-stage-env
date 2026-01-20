"""
FastAPI dependencies for dependency injection.
Centralized dependency management (DRY principle).
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Query

from app.config import Settings, get_settings
from app.core.slc_executor import SLCExecutor
from app.models.base import PaginationParams, SortParams


# === Configuration Dependencies ===

def get_settings_dependency() -> Settings:
    """Get application settings. Reusable dependency."""
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_settings_dependency)]


# === SLC Executor Dependencies ===

@lru_cache()
def get_slc_executor() -> SLCExecutor:
    """
    Get SLC executor instance. Singleton pattern.
    Cached for performance (DRY).
    """
    settings = get_settings()
    return SLCExecutor(
        cli_path=settings.slc_cli_path,
        project_root=settings.slc_project_root
    )


def get_slc_executor_dependency() -> SLCExecutor:
    """Get SLC executor dependency."""
    return get_slc_executor()


SLCExecutorDep = Annotated[SLCExecutor, Depends(get_slc_executor_dependency)]


# === Pagination Dependencies ===

def get_pagination_params(
    page: Annotated[int, Query(ge=1, description="Page number")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 20,
) -> PaginationParams:
    """Get pagination parameters from query. Reusable dependency."""
    return PaginationParams(page=page, page_size=page_size)


PaginationDep = Annotated[PaginationParams, Depends(get_pagination_params)]


# === Sorting Dependencies ===

def get_sort_params(
    sort_by: Annotated[str | None, Query(description="Field to sort by")] = None,
    sort_order: Annotated[str | None, Query(pattern="^(asc|desc)$", description="Sort order")] = "asc",
) -> SortParams:
    """Get sorting parameters from query. Reusable dependency."""
    return SortParams(sort_by=sort_by, sort_order=sort_order)


SortDep = Annotated[SortParams, Depends(get_sort_params)]


# === Search Dependencies ===

def get_search_query(
    q: Annotated[str | None, Query(max_length=200, description="Search query")] = None,
) -> str | None:
    """Get search query from query params. Reusable dependency."""
    return q.strip() if q else None


SearchDep = Annotated[str | None, Depends(get_search_query)]
