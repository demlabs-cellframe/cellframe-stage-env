"""
Central project-name management for Docker Compose resources.

Every Docker container, network, and volume is namespaced under a project name.
In sequential mode the default ``cellframe-stage`` is used.  In parallel mode
each worker process sets its own project name via an environment variable so
that suites execute in fully isolated Docker Compose projects.
"""

import os

DEFAULT_PROJECT_NAME = "cellframe-stage"
_ENV_KEY = "CELLFRAME_STAGE_PROJECT"


def get_project_name() -> str:
    """Return the active Docker Compose project name.

    Priority:
      1. ``CELLFRAME_STAGE_PROJECT`` environment variable (set per-worker).
      2. ``cellframe-stage`` (default, backward-compatible).
    """
    return os.environ.get(_ENV_KEY, DEFAULT_PROJECT_NAME)


def make_container_name(service: str) -> str:
    """Build a fully-qualified container name for *service*.

    >>> make_container_name("node-1")
    'cellframe-stage-node-1'
    """
    return f"{get_project_name()}-{service}"


def set_project_name(name: str) -> None:
    """Override the project name for the current process."""
    os.environ[_ENV_KEY] = name
