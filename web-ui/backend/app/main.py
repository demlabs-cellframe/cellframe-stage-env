"""
FastAPI application entry point.
Clean initialization with proper structure.
"""

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.exceptions import SLCWebError
from app.core.logging_config import configure_logging, get_logger
from app.models.responses import (
    ErrorResponse,
    HealthCheckItem,
    HealthCheckResponse,
    error_response
)

# Initialize settings and logging early
settings = get_settings()
configure_logging(log_level=settings.log_level, log_json=settings.log_json)
logger = get_logger(__name__)

# Track application start time for uptime
app_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.
    Handles startup and shutdown logic.
    """
    # Startup
    logger.info(
        "application_starting",
        version=settings.app_version,
        debug=settings.debug,
        host=settings.host,
        port=settings.port
    )
    
    # Initialize components
    # (File watcher, cache, etc. will be initialized here in future phases)
    
    logger.info("application_ready")
    
    yield
    
    # Shutdown
    logger.info("application_shutting_down")
    
    # Cleanup components
    # (Close file watcher, clear cache, etc.)
    
    logger.info("application_stopped")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="REST API for Smart Layered Context (SLC) system",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)


# === Middleware ===

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests with timing."""
    start_time = time.time()
    
    logger.info(
        "request_started",
        method=request.method,
        path=request.url.path,
        client=request.client.host if request.client else None
    )
    
    response = await call_next(request)
    
    duration_ms = (time.time() - start_time) * 1000
    
    logger.info(
        "request_completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration_ms, 2)
    )
    
    return response


# === Exception Handlers ===

@app.exception_handler(SLCWebError)
async def slc_web_error_handler(request: Request, exc: SLCWebError) -> JSONResponse:
    """Handle custom SLC Web errors."""
    logger.error(
        "slc_web_error",
        error_code=exc.code,
        error_message=exc.message,
        path=request.url.path,
        details=exc.details
    )
    
    response = ErrorResponse.from_exception(exc)
    
    # Determine status code based on error code
    status_code = 500  # Default to internal server error
    if exc.code == "VALIDATION_ERROR":
        status_code = 400
    elif exc.code == "RESOURCE_NOT_FOUND":
        status_code = 404
    elif exc.code == "COMMAND_NOT_ALLOWED":
        status_code = 403
    elif exc.code == "CONFIGURATION_ERROR":
        status_code = 500
    
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected errors. FAIL-FAST with proper logging."""
    logger.exception(
        "unhandled_exception",
        path=request.url.path,
        exc_type=type(exc).__name__,
        exc_message=str(exc)
    )
    
    # In debug mode, return detailed error
    if settings.debug:
        response = error_response(
            code="INTERNAL_ERROR",
            message=f"{type(exc).__name__}: {str(exc)}",
            details={"traceback": True}
        )
    else:
        response = error_response(
            code="INTERNAL_ERROR",
            message="An internal error occurred. Please contact support."
        )
    
    return JSONResponse(
        status_code=500,
        content=response.model_dump()
    )


# === Health Check Endpoints ===

@app.get("/health", response_model=HealthCheckResponse, tags=["Health"])
async def health_check() -> HealthCheckResponse:
    """
    Health check endpoint.
    Returns service status and basic metrics.
    """
    uptime = time.time() - app_start_time
    
    # Check SLC availability
    try:
        from app.dependencies import get_slc_executor
        executor = get_slc_executor()
        slc_start = time.time()
        result = await executor.execute("status", timeout=5.0)
        slc_latency = (time.time() - slc_start) * 1000
        slc_available = result.success
        slc_check = HealthCheckItem(
            status="healthy" if slc_available else "unhealthy",
            latency_ms=round(slc_latency, 2)
        )
    except Exception as e:
        slc_available = False
        slc_check = HealthCheckItem(
            status="unhealthy",
            message=str(e)
        )
    
    return HealthCheckResponse(
        status="healthy" if slc_available else "degraded",
        version=settings.app_version,
        uptime_seconds=round(uptime, 2),
        slc_available=slc_available,
        checks={"slc_cli": slc_check}
    )


@app.get("/health/ready", tags=["Health"])
async def readiness_check() -> dict[str, bool]:
    """
    Readiness check endpoint.
    Returns whether service is ready to accept requests.
    """
    # In future phases, check database, cache, etc.
    return {"ready": True}


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """Root endpoint with API info."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health"
    }


# === API Routes ===
# Will be imported and included in future phases:
# from app.api.routes import tasks, templates, context, system, analytics
# app.include_router(tasks.router, prefix="/api/tasks", tags=["Tasks"])
# etc.


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level=settings.log_level.lower()
    )
