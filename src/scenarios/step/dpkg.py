"""
Dpkg step executor — install/remove .deb packages inside Docker containers.

Uses DockerContainerManager helpers (docker_client, resolve_node_to_container,
exec_bash_command) instead of raw subprocess calls.
"""

import io
import tarfile
from pathlib import Path
from typing import List

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema_dpkg import DpkgStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)

CONTAINER_TMP = "/tmp"


class DpkgStepExecutor(StepExecutor):
    """Executor for dpkg install/remove steps."""

    def _expand_services(self, services, ctx) -> List[str]:
        if isinstance(services, str):
            expanded = ctx.substitute(services)
            if expanded.startswith('[') and expanded.endswith(']'):
                import ast
                try:
                    return ast.literal_eval(expanded)
                except (ValueError, SyntaxError):
                    return [expanded]
            return [s.strip() for s in expanded.split(',') if s.strip()]
        return [ctx.substitute(s) for s in services]

    async def execute(self, step: DpkgStep, ctx: RuntimeContext) -> None:
        operation = ctx.substitute(step.dpkg).lower()
        package = ctx.substitute(step.package)
        services = self._expand_services(step.services, ctx)

        if operation == "install":
            await self._install(package, services, ctx, fix_deps=step.fix_deps)
        elif operation == "remove":
            await self._remove(package, services, ctx)
        else:
            raise ScenarioExecutionError(
                f"Unknown dpkg operation '{operation}'. Expected 'install' or 'remove'.",
                step=step,
            )

    def _copy_file_to_container(self, container_name: str, host_path: Path, container_dir: str) -> str:
        """Copy a file into a container using Docker SDK put_archive. Returns container path."""
        container = self.container_manager.docker_client.containers.get(container_name)
        dest_path = f"{container_dir}/{host_path.name}"

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            tar.add(str(host_path), arcname=host_path.name)
        buf.seek(0)

        container.put_archive(container_dir, buf)
        return dest_path

    @staticmethod
    def _resolve_deb_path(host_path: str) -> Path:
        """Resolve a .deb path, supporting glob patterns (e.g. cellframe-node-cdb*.deb)."""
        p = Path(host_path)
        resolved = p.resolve()
        if resolved.exists():
            return resolved
        import glob as _glob
        candidates = sorted(_glob.glob(host_path), key=lambda f: Path(f).stat().st_mtime, reverse=True)
        if not candidates:
            parent = p.resolve().parent
            stem = p.stem
            candidates = sorted(parent.glob(f"{stem}*.deb"), key=lambda f: f.stat().st_mtime, reverse=True)
        if candidates:
            found = Path(candidates[0]).resolve()
            logger.info("dpkg_glob_resolved", original=host_path, resolved=str(found))
            return found
        raise ScenarioExecutionError(f"DEB package not found: {resolved} (glob also found nothing)")

    async def _install(self, host_path: str, services: List[str], ctx: RuntimeContext, fix_deps: bool = False) -> None:
        resolved = self._resolve_deb_path(host_path)

        deb_name = resolved.name

        for svc in services:
            container_name = self.container_manager.resolve_node_to_container(svc)
            logger.info("dpkg_install", container=container_name, package=str(resolved))

            container_deb = self._copy_file_to_container(container_name, resolved, CONTAINER_TMP)

            install_cmd = (
                f"DEBIAN_FRONTEND=noninteractive dpkg -i --force-depends --force-confold {container_deb} 2>&1"
            )
            if fix_deps:
                install_cmd += " ; apt-get install -f -y -qq 2>&1"
            install_cmd += f" && rm -f {container_deb}"

            result = await self.container_manager.exec_bash_command(
                install_cmd, node=svc, timeout=120,
            )

            if result["returncode"] != 0:
                raise ScenarioExecutionError(
                    f"dpkg install failed on {container_name} (rc={result['returncode']}): "
                    f"{result['stderr'] or result['stdout']}"
                )

            logger.info("dpkg_install_ok", container=container_name, output=result["stdout"].strip())

        ctx.add_result("dpkg", True, {"op": "install", "package": deb_name, "services": services})

    async def _remove(self, package_name: str, services: List[str], ctx: RuntimeContext) -> None:
        for svc in services:
            container_name = self.container_manager.resolve_node_to_container(svc)
            logger.info("dpkg_remove", container=container_name, package=package_name)

            result = await self.container_manager.exec_bash_command(
                f"dpkg --purge {package_name} 2>&1",
                node=svc,
                timeout=60,
            )

            if result["returncode"] != 0:
                raise ScenarioExecutionError(
                    f"dpkg remove failed on {container_name} (rc={result['returncode']}): "
                    f"{result['stderr'] or result['stdout']}"
                )

            logger.info("dpkg_remove_ok", container=container_name, output=result["stdout"].strip())

        ctx.add_result("dpkg", True, {"op": "remove", "package": package_name, "services": services})
