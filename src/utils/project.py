"""
Central project-name management for Docker Compose resources.

Every Docker container, network, and volume is namespaced under a project name.
In sequential mode the default ``cellframe-stage`` is used.  In parallel mode
each worker process sets its own project name via an environment variable so
that suites execute in fully isolated Docker Compose projects.
"""

import os
from pathlib import Path

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


def find_common_root(suite_path: Path, fallback: Path) -> Path:
    """Derive ``common_root`` from suite location by walking up to find ``common/``.

    Starting from *suite_path* (directory containing the suite descriptor),
    walk up at most 4 levels looking for a **real** (non-symlink) ``common/``
    sub-directory.  Returns the first ancestor that contains it, so that
    ``common_root / "common/defaults.yml"`` resolves naturally.

    Falls back to *fallback* when nothing is found.
    """
    current = suite_path.resolve()
    for _ in range(4):
        candidate = current / "common"
        if candidate.is_dir() and not candidate.is_symlink():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return fallback
