"""
Snapshot step executor.

Manages snapshot creation/restoration via scenario steps:
  - snapshot: create
    name: phase1
    
  - snapshot: restore
    name: phase1
    regenerate_certs: true   # unique node identity after restore
"""
from __future__ import annotations

from pathlib import Path

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import SnapshotStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class SnapshotStepExecutor(StepExecutor):
    """Executor for snapshot steps."""
    
    def __init__(self, container_manager, log_file=None, debug: bool = False,
                 compose_manager=None, base_path: Path = None, config_loader=None):
        """Initialize snapshot executor."""
        super().__init__(container_manager, log_file, debug)
        self.compose_manager = compose_manager
        self.base_path = base_path
        self.config_loader = config_loader
    
    async def execute(self, step: SnapshotStep, ctx: RuntimeContext) -> None:
        """Execute snapshot step."""
        # Substitute variables in name
        snapshot_name = ctx.substitute(step.name)
        operation = ctx.substitute(step.snapshot)
        
        logger.info(f"Snapshot: {operation} '{snapshot_name}'" + 
                   (" (base)" if step.is_base else ""))
        
        # Get SnapshotManager from context
        if not hasattr(ctx, 'snapshot_manager') or not ctx.snapshot_manager:
            raise ScenarioExecutionError(
                "SnapshotManager not available in context.",
                step=step
            )
        
        snapshot_manager = ctx.snapshot_manager
        
        try:
            if operation == "create":
                await self._execute_create(step, snapshot_name, snapshot_manager, ctx)
            elif operation == "restore":
                await self._execute_restore(step, snapshot_name, snapshot_manager, ctx)
            elif operation == "verify":
                await self._execute_verify(step, snapshot_name, snapshot_manager, ctx)
            elif operation == "delete":
                await self._execute_delete(step, snapshot_name, snapshot_manager, ctx)
            else:
                raise ScenarioExecutionError(f"Unknown snapshot operation: {operation}", step=step)
            
            logger.info(f"✅ Snapshot '{operation}' completed: {snapshot_name}")
            ctx.add_result("snapshot", True, {
                "operation": operation, 
                "name": snapshot_name,
                "is_base": step.is_base
            })
            
        except Exception as e:
            error_msg = f"Snapshot operation failed: {str(e)}"
            logger.error(error_msg)
            ctx.add_result("snapshot", False, {"operation": operation, "error": str(e)})
            raise ScenarioExecutionError(error_msg, step=step)
    
    async def _execute_create(
        self, 
        step: SnapshotStep, 
        name: str, 
        manager, 
        ctx: RuntimeContext
    ) -> None:
        """Create snapshot.

        When ``stop_containers`` is true (default), containers are stopped
        before snapshotting to guarantee MDBX/GDB file consistency.
        When ``restart_after`` is also true (default), they are brought
        back up after the snapshot is written.
        """
        stopped_services = None
        if step.stop_containers and self.compose_manager:
            stopped_services = [
                c.labels.get("com.docker.compose.service")
                for c in self.compose_manager.ps()
                if c.status == "running"
                and c.labels.get("com.docker.compose.service")
            ]
            logger.info("stopping_containers_for_snapshot",
                        services=stopped_services)
            self.compose_manager.stop()

        clone_images = self._resolve_clone_images(step, ctx)
        
        result = await manager.create_snapshot(name, clone_images=clone_images)
        if not result:
            raise RuntimeError(f"Failed to create snapshot: {name}")
        
        if step.is_base:
            if hasattr(manager, 'snapshot') and manager.snapshot:
                marker_path = manager.snapshot.snapshots_path / f"{name}.base"
                marker_path.write_text(f"topology={ctx.variables.get('topology_name', 'default')}\n")
                logger.info("base_snapshot_marker_created", name=name)

        if stopped_services and step.restart_after and self.compose_manager:
            logger.info("restarting_containers_after_snapshot",
                        services=stopped_services)
            self.compose_manager.up(
                services=stopped_services,
                detach=True, wait=False, no_build=True,
            )
            if self.base_path:
                restarted_svcs = self._sync_plugin_configs(ctx)
                if restarted_svcs:
                    await self._wait_for_nodes_ready(restarted_svcs, timeout=90)
    
    async def _execute_restore(
        self, 
        step: SnapshotStep, 
        name: str, 
        manager, 
        ctx: RuntimeContext
    ) -> None:
        """Restore snapshot with proper container lifecycle.
        
        Stops containers before restore to prevent bind mount invalidation,
        then restarts them (from committed images if available).
        If ``regenerate_certs`` is set, every node receives a fresh
        ``node-addr.dcert`` so that each container has a unique address.
        If ``wait_ready`` is set, waits for cellframe nodes to become
        CLI-responsive (and optionally runs a custom readiness check).
        """
        running_services = None
        if self.compose_manager:
            running_services = [
                c.labels.get("com.docker.compose.service")
                for c in self.compose_manager.ps()
                if c.status == "running"
                and c.labels.get("com.docker.compose.service")
            ]
            logger.info("removing_containers_before_restore",
                       services=running_services)
            self.compose_manager.down(volumes=False)
        
        result = await manager.restore_snapshot(name)
        if not result:
            raise RuntimeError(f"Failed to restore snapshot: {name}")

        if step.regenerate_certs:
            self._regenerate_certs_after_restore(ctx)
        
        if self.compose_manager:
            logger.info("restarting_containers_after_restore",
                       services=running_services)
            self.compose_manager.up(
                services=running_services or None,
                detach=True, wait=False, no_build=True,
            )

        plugin_restarted: list[str] = []
        if self.compose_manager and self.base_path:
            plugin_restarted = self._sync_plugin_configs(ctx)

        if step.wait_ready and self.compose_manager:
            wait_nodes = self._resolve_wait_ready_nodes(step, ctx)
            all_nodes = list(dict.fromkeys(wait_nodes + plugin_restarted))
            if all_nodes:
                custom_cmd = ctx.substitute(step.wait_ready_check) if step.wait_ready_check else None
                await self._wait_for_nodes_ready(
                    all_nodes,
                    timeout=step.wait_ready_timeout,
                    custom_check_cmd=custom_cmd,
                )
        elif plugin_restarted and self.compose_manager:
            await self._wait_for_nodes_ready(plugin_restarted, timeout=90)

    def _resolve_wait_ready_nodes(
        self, step: SnapshotStep, ctx: RuntimeContext
    ) -> list[str]:
        """Determine which nodes to wait for after restore.

        Returns a list of service names whose CLI readiness should be verified.
        When ``wait_ready`` is ``True``, auto-detects cellframe node services
        by looking for containers that have ``NODE_ID`` in their environment
        (set by the compose generator for every cellframe-node service).
        """
        if isinstance(step.wait_ready, list):
            return [ctx.substitute(n) for n in step.wait_ready]

        if step.wait_ready is True:
            try:
                nodes = []
                for c in self.compose_manager.ps():
                    svc = c.labels.get("com.docker.compose.service")
                    if not svc:
                        continue
                    env_list = c.attrs.get("Config", {}).get("Env", [])
                    if any(e.startswith("NODE_ID=") for e in env_list):
                        nodes.append(svc)
                if nodes:
                    logger.info("wait_ready_auto_detected", nodes=nodes)
                return nodes
            except Exception as e:
                logger.warning("wait_ready_auto_detect_failed", error=str(e))
                return []

        return []

    async def _wait_for_nodes_ready(
        self,
        nodes: list[str],
        timeout: int = 90,
        custom_check_cmd: str | None = None,
    ) -> None:
        """Poll cellframe-node CLI on each node until it responds.

        Per-node two-phase check within a single loop:
        1. ``basic``: ``cellframe-node-cli version`` succeeds (daemon is up).
        2. ``custom`` (if *custom_check_cmd* given):
           ``cellframe-node-cli <cmd>`` succeeds without "can't recognize".

        Raises ``RuntimeError`` if any node fails to become ready within
        *timeout* seconds.
        """
        import asyncio as _aio
        import time

        interval = 3
        start = time.monotonic()
        deadline = start + timeout
        logger.info("wait_ready_start", nodes=nodes, timeout=timeout,
                     custom_check=custom_check_cmd)

        phase: dict[str, str] = {n: "basic" for n in nodes}

        while time.monotonic() < deadline:
            active = [n for n, p in phase.items() if p != "done"]
            if not active:
                break
            for node in active:
                try:
                    if phase[node] == "basic":
                        ec, out = self.compose_manager.exec(
                            node, ["cellframe-node-cli", "version"]
                        )
                        if ec == 0 and out.strip():
                            logger.info("wait_ready_node_cli_ok", node=node)
                            phase[node] = "custom" if custom_check_cmd else "done"
                    elif phase[node] == "custom":
                        ec, out = self.compose_manager.exec(
                            node,
                            ["cellframe-node-cli"] + custom_check_cmd.split(),
                        )
                        if ec == 0 and "can't recognize" not in out:
                            logger.info("wait_ready_custom_ok",
                                        node=node, cmd=custom_check_cmd)
                            phase[node] = "done"
                except Exception:
                    pass
            if any(p != "done" for p in phase.values()):
                await _aio.sleep(interval)

        failed = {n: p for n, p in phase.items() if p != "done"}
        elapsed = int(time.monotonic() - start)
        if failed:
            logger.error("wait_ready_timeout", failed=failed, elapsed_s=elapsed)
            raise RuntimeError(
                f"Nodes not ready after {elapsed}s: "
                + ", ".join(f"{n} (phase={p})" for n, p in failed.items())
            )
        logger.info("wait_ready_complete", elapsed_s=elapsed,
                     nodes_checked=len(nodes))

    def _sync_plugin_configs(self, ctx: RuntimeContext) -> list[str]:
        """Push non-bind-mounted plugin configs into containers after restore.

        ``lib/plugins/`` is NOT bind-mounted (that would shadow the .so from
        the Docker image).  After compose.down()+up() or stop()+up() the
        container-local copy of rendered configs (created earlier by the
        ``config:`` step via docker cp) is lost.  This method re-pushes
        host-side plugin configs and restarts affected containers so the
        daemon picks up the updated config.

        Returns a list of *service names* whose containers were restarted.
        """
        import re
        import subprocess
        import time as _time

        cache_dir = self._resolve_cache_dir()
        if not cache_dir:
            return []
        data_dir = cache_dir / "data"
        if not data_dir.exists():
            return []

        node_dirs: dict[int, Path] = {}
        for d in data_dir.iterdir():
            m = re.match(r'^node(\d+)$', d.name)
            if m and d.is_dir():
                node_dirs[int(m.group(1))] = d

        if not node_dirs:
            return []

        container_info: list[tuple[str, str, int]] = []
        deadline = _time.monotonic() + 30
        while _time.monotonic() < deadline:
            container_info.clear()
            try:
                for c in self.compose_manager.ps():
                    if c.status != "running":
                        continue
                    svc = c.labels.get("com.docker.compose.service")
                    if not svc:
                        continue
                    env_list = c.attrs.get("Config", {}).get("Env", [])
                    for e in env_list:
                        if e.startswith("NODE_ID="):
                            nid = int(e.split("=", 1)[1])
                            container_info.append((c.name, svc, nid))
                            break
            except Exception as exc:
                logger.warning("sync_plugins_ps_failed", error=str(exc))
            if container_info:
                break
            _time.sleep(2)

        if not container_info:
            logger.warning("sync_plugins_no_running_containers")
            return []

        affected_services: list[str] = []
        for container_name, svc_name, nid in container_info:
            node_dir = node_dirs.get(nid)
            if not node_dir:
                continue
            host_plugins = node_dir / "lib" / "plugins"
            if not host_plugins.is_dir():
                continue
            pushed = False
            for plugin_dir in host_plugins.iterdir():
                if not plugin_dir.is_dir():
                    continue
                for cfg_file in plugin_dir.iterdir():
                    if not cfg_file.is_file() or cfg_file.suffix == ".so":
                        continue
                    dest = f"/opt/cellframe-node/var/lib/plugins/{plugin_dir.name}/{cfg_file.name}"
                    try:
                        subprocess.run(
                            ["docker", "cp", str(cfg_file), f"{container_name}:{dest}"],
                            capture_output=True, timeout=10, check=True,
                        )
                        pushed = True
                    except Exception as exc:
                        logger.warning("sync_plugin_config_failed",
                                       file=str(cfg_file), container=container_name,
                                       error=str(exc))
            if pushed:
                affected_services.append(svc_name)

        expected = len(container_info)
        if expected and not affected_services:
            logger.error("sync_plugin_configs_none_pushed",
                         expected=expected,
                         message="all docker cp attempts failed — configs NOT applied")

        if affected_services:
            logger.info("plugin_configs_synced",
                        count=len(affected_services),
                        services=affected_services)
            try:
                self.compose_manager.restart(services=affected_services)
                logger.info("containers_restarted_for_config",
                            services=affected_services)
            except Exception as exc:
                logger.error("containers_restart_failed",
                             services=affected_services, error=str(exc))

        return affected_services

    def _resolve_cache_dir(self) -> Path | None:
        if not self.base_path:
            return None
        cache_rel = "../../cache"
        if self.config_loader:
            paths = self.config_loader.get_paths_config()
            cache_rel = paths.get('cache_dir', cache_rel)
        p = Path(cache_rel)
        if not p.is_absolute():
            p = self.base_path / p
        p = p.resolve()
        return p if p.exists() else None

    @staticmethod
    def _resolve_clone_images(step: SnapshotStep, ctx: RuntimeContext) -> dict | None:
        """Resolve clone_images values after variable substitution.

        Values may be:
        - a Python list literal in YAML: ``[node-8]``
        - a ``{{variable}}`` template that resolves to a list
        - a plain service name string
        """
        if not step.clone_images:
            return None
        import ast

        resolved: dict = {}
        for src_key, targets_raw in step.clone_images.items():
            src = ctx.substitute(str(src_key))
            if isinstance(targets_raw, str):
                subst = ctx.substitute(targets_raw)
                if subst.startswith('[') and subst.endswith(']'):
                    try:
                        targets_raw = ast.literal_eval(subst)
                    except (ValueError, SyntaxError):
                        targets_raw = [subst]
                else:
                    targets_raw = [subst]
            if isinstance(targets_raw, list):
                targets = [ctx.substitute(str(t)) for t in targets_raw]
            else:
                targets = [str(targets_raw)]
            resolved[src] = targets
        return resolved

    def _regenerate_certs_after_restore(self, ctx: RuntimeContext) -> None:
        """Regenerate unique node-addr certs for ALL nodes found in cache/data/.

        Scans every ``node<N>`` directory — base topology nodes, node_compose_gen
        nodes, fresh nodes — and generates a fresh ``node-addr.dcert`` for each.
        """
        from ...cli.test_commands import regenerate_node_certs

        cache_dir = self._resolve_cache_dir()
        if not cache_dir:
            logger.warning("regenerate_certs_skip_no_cache")
            return

        data_dir = cache_dir / "data"
        if not data_dir.exists():
            return

        import re
        nodes: dict = {}
        for d in sorted(data_dir.iterdir()):
            m = re.match(r'^node(\d+)$', d.name)
            if m and d.is_dir():
                node_id = int(m.group(1))
                nodes[node_id] = d.name

        if not nodes:
            logger.info("regenerate_certs_no_nodes_found")
            return

        logger.info("regenerating_certs_after_restore",
                     node_count=len(nodes),
                     node_ids=sorted(nodes.keys()))
        addr_map = regenerate_node_certs(
            cache_dir, nodes, self.base_path,
            logger_fn=lambda msg: logger.info(msg),
            warn_fn=lambda msg: logger.warning(msg),
        )
        logger.info("regenerated_certs", count=len(addr_map))
    
    async def _execute_verify(
        self, 
        step: SnapshotStep, 
        name: str, 
        manager, 
        ctx: RuntimeContext
    ) -> None:
        """Verify snapshot exists. With save=varname, stores True/False instead of raising."""
        exists = (
            manager.snapshot.exists(name)
            if hasattr(manager, 'snapshot') and manager.snapshot
            else False
        )

        if step.save:
            ctx.set_variable(step.save, exists)
            logger.info("snapshot_verify_result", name=name, exists=exists, saved_to=step.save)
        elif not exists:
            raise RuntimeError(f"Snapshot not found: {name}")
        else:
            logger.info("snapshot_verified", name=name)
    
    async def _execute_delete(
        self, 
        step: SnapshotStep, 
        name: str, 
        manager, 
        ctx: RuntimeContext
    ) -> None:
        """Delete snapshot."""
        if hasattr(manager, 'delete_snapshot'):
            result = await manager.delete_snapshot(name)
            if not result:
                logger.warning("snapshot_delete_failed", name=name)
        else:
            logger.warning("snapshot_delete_not_supported")


