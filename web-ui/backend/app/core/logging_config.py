"""
Centralized logging configuration using structlog.
DRY principle: configure once, use everywhere.
"""

import logging
import sys
from typing import Any, Dict

import structlog
from structlog.types import Processor


def configure_logging(
    log_level: str = "INFO",
    log_json: bool = False
) -> None:
    """
    Configure structured logging for the application.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_json: Output logs in JSON format (for production)
    """
    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper())
    )
    
    # Build processors chain
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    
    # Add JSON or console renderer
    if log_json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a configured logger instance.
    
    Args:
        name: Logger name (usually __name__)
    
    Returns:
        Configured logger instance
    """
    return structlog.get_logger(name)


def log_context(**kwargs: Any) -> Dict[str, Any]:
    """
    Create logging context dictionary.
    Helper for consistent context logging.
    
    Args:
        **kwargs: Context key-value pairs
    
    Returns:
        Context dictionary
    """
    return kwargs
