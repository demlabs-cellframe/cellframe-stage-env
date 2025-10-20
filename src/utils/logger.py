"""
Structured logging configuration using structlog.

Provides consistent logging across all stage environment modules with:
- Structured context
- Colored output for terminal
- JSON output for CI/CD
- Performance timing
"""

import logging
import sys
from typing import Any

import structlog
from rich.console import Console

# Console for rich output
console = Console()


def setup_logging(verbose: bool = False, json_output: bool = False) -> None:
    """
    Configure structured logging for stage environment.
    
    Args:
        verbose: Enable debug level logging
        json_output: Output logs as JSON (for CI/CD)
    """
    log_level = logging.DEBUG if verbose else logging.INFO
    
    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )
    
    # Processors for structlog
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    
    if json_output:
        # JSON output for CI/CD
        processors.extend([
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ])
    else:
        # Human-readable colored output
        processors.extend([
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback,
            ),
        ])
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """
    Get a structured logger for a module.
    
    Args:
        name: Module name (usually __name__)
        
    Returns:
        Configured structlog logger
        
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("node_started", node_id=1, role="master")
    """
    return structlog.get_logger(name)


class LogContext:
    """
    Context manager for temporary log context.
    
    Example:
        >>> with LogContext(node_id=1, action="start"):
        ...     logger.info("starting_node")  # Will include node_id and action
    """
    
    def __init__(self, **context: Any):
        self.context = context
        self.token = None
    
    def __enter__(self):
        self.token = structlog.contextvars.bind_contextvars(**self.context)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        structlog.contextvars.unbind_contextvars(*self.context.keys())


# Module-level logger
logger = get_logger(__name__)

