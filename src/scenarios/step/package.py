"""
Runtime package installer for scenarios.

Installs DEB packages into running Docker containers via docker cp + dpkg -i.
Used for per-scenario package requirements that aren't baked into the image.
"""

import asyncio
import tempfile
from pathlib import Path
from typing import List, Optional, Union

from src.utils.logger import get_logger
from .base import StepExecutor
from ..schema import AptPackage, LocalPackage, URLPackage, PackageSpec

logger = get_logger(__name__)


class PackageInstaller(StepExecutor):
    """Install packages into running containers at runtime."""

    def __init__(self, container_manager, log_file=None, debug=False,
                 resolve_node_alias_callback=None, base_path: Optional[Path] = None):
        super().__init__(container_manager, log_file, debug)
        self.resolve_node_alias_callback = resolve_node_alias_callback
        self.base_path = base_path

    def _resolve_nodes(self, node_spec: Union[str, List[str]]) -> List[str]:
        nodes = [node_spec] if isinstance(node_spec, str) else list(node_spec)
        resolved = []
        for n in nodes:
            if self.resolve_node_alias_callback:
                n = self.resolve_node_alias_callback(n)
            resolved.append(n)
        return resolved

    async def install_packages(self, packages: List[PackageSpec]) -> None:
        for pkg in packages:
            if isinstance(pkg, LocalPackage):
                await self._install_local(pkg)
            elif isinstance(pkg, URLPackage):
                await self._install_url(pkg)
            elif isinstance(pkg, AptPackage):
                await self._install_apt(pkg)

    async def _install_local(self, pkg: LocalPackage) -> None:
        src = Path(pkg.local)
        if not src.is_absolute() and self.base_path:
            src = (self.base_path / src).resolve()

        if not src.exists():
            raise FileNotFoundError(f"Local package not found: {src}")

        nodes = self._resolve_nodes(pkg.node)
        for node in nodes:
            container = self.container_manager._get_container_name(node)
            logger.info("installing_local_package", node=node, package=src.name)

            cp_proc = await asyncio.create_subprocess_exec(
                "docker", "cp", str(src), f"{container}:/tmp/{src.name}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await cp_proc.wait()

            result = await self.container_manager.exec_bash_command(
                f"DEBIAN_FRONTEND=noninteractive dpkg -i --force-depends --force-confold /tmp/{src.name} && "
                f"apt-get install -f -y -qq 2>&1 || true && rm -f /tmp/{src.name}",
                node=node, timeout=120
            )
            logger.info("local_package_installed", node=node, package=src.name,
                       exit_code=result.get('exit_code', -1))

    async def _install_url(self, pkg: URLPackage) -> None:
        nodes = self._resolve_nodes(pkg.node)
        fname = pkg.url.rsplit('/', 1)[-1]
        for node in nodes:
            logger.info("installing_url_package", node=node, url=pkg.url)
            result = await self.container_manager.exec_bash_command(
                f"cd /tmp && wget -q '{pkg.url}' -O '{fname}' && "
                f"DEBIAN_FRONTEND=noninteractive dpkg -i --force-depends --force-confold '/tmp/{fname}' && "
                f"apt-get install -f -y -qq 2>&1 || true && rm -f '/tmp/{fname}'",
                node=node, timeout=180
            )
            logger.info("url_package_installed", node=node, package=fname,
                       exit_code=result.get('exit_code', -1))

    async def _install_apt(self, pkg: AptPackage) -> None:
        nodes = self._resolve_nodes(pkg.node)
        pkg_list = " ".join(pkg.apt)
        for node in nodes:
            logger.info("installing_apt_packages", node=node, packages=pkg_list)
            result = await self.container_manager.exec_bash_command(
                f"apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq {pkg_list}",
                node=node, timeout=180
            )
            logger.info("apt_packages_installed", node=node, packages=pkg_list,
                       exit_code=result.get('exit_code', -1))
