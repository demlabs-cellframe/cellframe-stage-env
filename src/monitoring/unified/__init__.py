"""
Unified waiter registry for YAML scenarios.

Provides centralized access to all waiters with YAML-friendly interface.
"""

from .wait_registry import WaitRegistry, WAITER_REGISTRY

__all__ = [
    'WaitRegistry',
    'WAITER_REGISTRY',
]

