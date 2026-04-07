"""
Unified monitoring manager.

Provides centralized access to all monitoring services:
- Datum tracking (lifecycle monitoring)
- Health checking (nodes, RPC endpoints)

Usage:
    # Get singleton instance
    monitor = MonitoringManager.get_instance()
    
    # Access datum monitor
    result = await monitor.datum.wait_for_datum(...)
    
    # Access health checker
    health = await monitor.health.check_http(...)
"""

from pathlib import Path
from typing import Optional

from .datum import DatumMonitor
from .health import HealthChecker


class MonitoringManager:
    """
    Manager for all monitoring services.

    Supports both singleton access (backward-compatible, sequential mode)
    and per-shard instances (parallel mode — keyed by *shard_key*).
    """

    _instances: dict[str, "MonitoringManager"] = {}

    def __init__(
        self,
        node_cli_path: str = "cellframe-node-cli",
        log_file: Optional[Path] = None,
    ):
        self.node_cli_path = node_cli_path
        self.log_file = log_file

        self.datum = DatumMonitor(
            node_cli_path=node_cli_path,
            log_file=log_file,
        )
        self.health = HealthChecker(timeout=10.0)

    @classmethod
    def get_instance(
        cls,
        node_cli_path: Optional[str] = None,
        log_file: Optional[Path] = None,
        shard_key: str = "_default",
    ) -> "MonitoringManager":
        """Get or create an instance keyed by *shard_key*."""
        if shard_key not in cls._instances:
            cls._instances[shard_key] = MonitoringManager(
                node_cli_path=node_cli_path or "cellframe-node-cli",
                log_file=log_file,
            )
        return cls._instances[shard_key]

    @classmethod
    def reset_instance(cls, shard_key: Optional[str] = None) -> None:
        """Reset one or all monitoring instances."""
        if shard_key is None:
            cls._instances.clear()
        else:
            cls._instances.pop(shard_key, None)
