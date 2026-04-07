"""
Shard context for parallel suite execution.

A *shard* is a fully isolated Docker environment in which a single test
suite executes.  ``ShardContext`` computes all derived configuration values
from a numeric ``shard_id`` and the base project configuration.
"""

from __future__ import annotations

import ipaddress
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.utils.project import DEFAULT_PROJECT_NAME, set_project_name


@dataclass
class ShardContext:
    """Isolated execution context assigned to a test suite."""

    shard_id: int

    # ---- base values (read from stage-env.cfg / topology) ----
    _base_project: str = DEFAULT_PROJECT_NAME
    _base_subnet: str = "172.22.0.0/24"
    _base_ip: str = "172.22.0.10"
    _base_http_port: int = 18079
    _base_rpc_port: int = 18080
    _base_p2p_port: int = 18081
    _base_cf_port: int = 18082
    _base_cache_dir: str = "../../cache"

    # ---- derived (computed in __post_init__) ----
    project_name: str = field(init=False)
    subnet: str = field(init=False)
    base_ip: str = field(init=False)
    base_http_port: int = field(init=False)
    base_rpc_port: int = field(init=False)
    base_p2p_port: int = field(init=False)
    base_cf_port: int = field(init=False)
    cache_dir: str = field(init=False)

    # Max nodes per shard (ports allocated in contiguous block)
    NODE_SLOTS: int = 20

    def __post_init__(self) -> None:
        self.project_name = f"{self._base_project}-{self.shard_id}"

        # Shift subnet by shard_id, respecting prefix length.
        # /16 → shift second octet (stride 65536)
        # /24 → shift third octet  (stride 256)
        net = ipaddress.ip_network(self._base_subnet, strict=False)
        stride = 2 ** (32 - net.prefixlen)  # host addresses per subnet
        shifted_net = ipaddress.ip_network(
            (int(net.network_address) + (self.shard_id * stride), net.prefixlen),
        )
        self.subnet = str(shifted_net)

        ip = ipaddress.ip_address(self._base_ip)
        self.base_ip = str(ipaddress.ip_address(int(ip) + self.shard_id * stride))

        port_offset = self.shard_id * self.NODE_SLOTS
        self.base_http_port = self._base_http_port + port_offset
        self.base_rpc_port = self._base_rpc_port + port_offset
        self.base_p2p_port = self._base_p2p_port + port_offset
        self.base_cf_port = self._base_cf_port + port_offset

        self.cache_dir = str(Path(self._base_cache_dir) / f"shard-{self.shard_id}")

    # ------------------------------------------------------------------
    def activate(self) -> None:
        """Set the project name for the current process (env var)."""
        set_project_name(self.project_name)

    def prepare_cache(self, base_path: Path, source_cache: Optional[Path] = None) -> Path:
        """Create the shard's cache directory structure.

        The snapshot `.sqfs` file is NOT copied — all shards share the base
        cache's snapshot directory (read-only).  ``SnapshotManager`` extracts
        data into ``cache_path`` which is set to the shard's own directory.

        Returns the resolved cache directory.
        """
        cache = (base_path / self.cache_dir).resolve()
        cache.mkdir(parents=True, exist_ok=True)
        for sub in ("configs", "data", "crash-artifacts", "cellframe-packages"):
            (cache / sub).mkdir(exist_ok=True)

        # Copy deb packages from base cache so Docker build context works
        if source_cache and source_cache.is_dir():
            pkg_src = source_cache / "cellframe-packages"
            pkg_dst = cache / "cellframe-packages"
            if pkg_src.is_dir():
                for deb in pkg_src.glob("*.deb"):
                    dst = pkg_dst / deb.name
                    if not dst.exists():
                        shutil.copy2(deb, dst)

        return cache

    @classmethod
    def from_topology(cls, shard_id: int, topology) -> ShardContext:
        """Create a shard from existing topology settings."""
        settings = topology.network_settings
        return cls(
            shard_id=shard_id,
            _base_project=DEFAULT_PROJECT_NAME,
            _base_subnet=settings.subnet,
            _base_ip=settings.base_ip,
            _base_http_port=settings.base_http_port,
            _base_rpc_port=settings.base_rpc_port,
            _base_p2p_port=settings.base_p2p_port,
            _base_cf_port=settings.base_cf_port,
        )
