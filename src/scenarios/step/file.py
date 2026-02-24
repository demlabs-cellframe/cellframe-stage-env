"""
Runtime file installer for scenarios.

Copies files into running Docker containers via docker cp.
Used for per-scenario file placement (configs, data files, etc.).
"""

import asyncio
import tempfile
from pathlib import Path
from typing import List, Optional, Union

from src.utils.logger import get_logger
from .base import StepExecutor
from ..schema import FileFromSource, FileFromContent, FileSpec

logger = get_logger(__name__)


class FileInstaller(StepExecutor):
    """Install files into running containers at runtime."""

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

    async def install_files(self, files: List[FileSpec]) -> None:
        for f in files:
            if isinstance(f, FileFromSource):
                await self._copy_from_source(f)
            elif isinstance(f, FileFromContent):
                await self._create_from_content(f)

    async def _copy_from_source(self, spec: FileFromSource) -> None:
        src = Path(spec.src)
        if not src.is_absolute() and self.base_path:
            src = (self.base_path / src).resolve()

        if not src.exists():
            raise FileNotFoundError(f"Source file not found: {src}")

        nodes = self._resolve_nodes(spec.node)
        for node in nodes:
            container = self.container_manager._get_container_name(node)
            logger.info("copying_file", node=node, src=str(src), dst=spec.dst)

            cp_proc = await asyncio.create_subprocess_exec(
                "docker", "cp", str(src), f"{container}:{spec.dst}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await cp_proc.communicate()
            if cp_proc.returncode != 0:
                raise RuntimeError(f"docker cp failed for {node}: {stderr.decode()}")

            if spec.mode:
                await self.container_manager.exec_bash_command(
                    f"chmod {spec.mode} '{spec.dst}'",
                    node=node, timeout=10
                )
            logger.info("file_copied", node=node, dst=spec.dst)

    async def _create_from_content(self, spec: FileFromContent) -> None:
        nodes = self._resolve_nodes(spec.node)
        for node in nodes:
            container = self.container_manager._get_container_name(node)
            logger.info("creating_file", node=node, dst=spec.dst)

            with tempfile.NamedTemporaryFile(mode='w', suffix='.tmp', delete=False) as tmp:
                tmp.write(spec.content)
                tmp_path = tmp.name

            try:
                cp_proc = await asyncio.create_subprocess_exec(
                    "docker", "cp", tmp_path, f"{container}:{spec.dst}",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                _, stderr = await cp_proc.communicate()
                if cp_proc.returncode != 0:
                    raise RuntimeError(f"docker cp failed for {node}: {stderr.decode()}")
            finally:
                Path(tmp_path).unlink(missing_ok=True)

            if spec.mode:
                await self.container_manager.exec_bash_command(
                    f"chmod {spec.mode} '{spec.dst}'",
                    node=node, timeout=10
                )
            logger.info("file_created", node=node, dst=spec.dst)
