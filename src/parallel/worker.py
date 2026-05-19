"""
Worker function for parallel suite execution.

Each worker runs in a separate *process* (via ``multiprocessing``).  Before
doing any Docker work it activates its :class:`ShardContext`, which sets the
project-name environment variable so that every ``get_project_name()`` call
in child code returns the shard-specific name.
"""

from __future__ import annotations

import asyncio
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.project import set_project_name, find_common_root


@dataclass
class SuiteTask:
    """Serialisable description of a suite to execute."""

    suite_key: str
    suite_dir: Path
    descriptor_path: Path
    scenario_files: List[Path]
    test_type: str


@dataclass
class SuiteResult:
    """Serialisable result of a suite execution."""

    suite_key: str
    passed: int = 0
    failed: int = 0
    total: int = 0
    scenario_results: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    duration_seconds: float = 0.0


def run_suite_in_shard(
    shard_id: int,
    task: SuiteTask,
    base_path: Path,
    config_path: Optional[Path],
    run_dir_base: Path,
    debug_mode: bool,
    topology_name: str,
    cli_params: Dict[str, str],
    shard_settings: Dict[str, Any],
) -> SuiteResult:
    """Execute a single suite inside an isolated shard.

    This function is the *target* for ``multiprocessing.Process`` /
    ``ProcessPoolExecutor``.  It must be a module-level function (picklable).

    Args:
        shard_id: Numeric shard identifier.
        task: Suite descriptor.
        base_path: Absolute path to ``tools/stage-env/``.
        config_path: Path to ``stage-env.cfg`` (or *None*).
        run_dir_base: Root artifact directory for the whole run.
        debug_mode: Scenario debug flag.
        topology_name: Network topology name (usually ``"default"``).
        cli_params: User-supplied ``-P key=val`` params.
        shard_settings: Dict with base topology values for :class:`ShardContext`.

    Returns:
        :class:`SuiteResult` with per-scenario verdicts.
    """
    import time
    t0 = time.monotonic()

    from .shard import ShardContext

    shard = ShardContext(shard_id=shard_id, **shard_settings)
    shard.activate()
    source_cache = (base_path / shard_settings.get("_base_cache_dir", "../../cache")).resolve()
    shard.prepare_cache(base_path, source_cache=source_cache)

    result = SuiteResult(suite_key=task.suite_key)

    try:
        _run_suite_sync(
            shard, task, base_path, config_path, run_dir_base,
            debug_mode, topology_name, cli_params, result,
        )
    except Exception as exc:
        result.error = f"{exc}\n{traceback.format_exc()}"
    finally:
        result.duration_seconds = time.monotonic() - t0
        _cleanup_shard(shard, base_path)

    return result


# ------------------------------------------------------------------
# Internal helpers (run inside the worker process)
# ------------------------------------------------------------------

def _run_suite_sync(
    shard,
    task: SuiteTask,
    base_path: Path,
    config_path: Optional[Path],
    run_dir_base: Path,
    debug_mode: bool,
    topology_name: str,
    cli_params: Dict[str, str],
    result: SuiteResult,
) -> None:
    """Synchronous wrapper that drives the async scenario executor."""
    from ..config.manager import get_config_loader
    from ..network.manager import NetworkManager
    from ..monitoring.manager import MonitoringManager
    from ..scenarios.parser import ScenarioParser, SuiteSetupParser
    from ..scenarios.executor import ScenarioExecutor, ScenarioExecutionError
    from ..scenarios.schema import SuiteDescriptor
    from ..scenarios.extractors import set_debug_mode

    set_debug_mode(debug_mode)
    config_loader = get_config_loader()

    network_mgr = NetworkManager(
        base_path, topology_name=topology_name, config_path=config_path,
    )
    network_mgr.compose.project_name = shard.project_name
    network_mgr.keep_running = False

    # Override network_settings so generated compose uses shard's subnet/ports
    settings = network_mgr.topology.network_settings
    settings.subnet = shard.subnet
    settings.base_ip = shard.base_ip
    settings.base_http_port = shard.base_http_port
    settings.base_rpc_port = shard.base_rpc_port
    settings.base_p2p_port = shard.base_p2p_port
    settings.base_cf_port = shard.base_cf_port

    # Override cache_dir so volume mounts and node data are shard-isolated
    network_mgr.paths_config['cache_dir'] = shard.cache_dir

    shard_cache = (base_path / shard.cache_dir).resolve()
    if network_mgr.snapshot_manager.snapshot is not None:
        # cache_path → shard's cache (unsquashfs extracts data here)
        network_mgr.snapshot_manager.snapshot.cache_path = shard_cache
        # snapshots_path stays at BASE cache — the .sqfs file is shared,
        # genesis ran once and all shards restore from the same image
        # (DO NOT point to shard cache — there is no .sqfs there)

    # Compose file per-shard so they don't clobber each other
    network_mgr.compose.compose_file = (
        network_mgr.compose.project_dir / f"docker-compose.shard-{shard.shard_id}.yml"
    )

    # Monitoring per-shard
    shard_key = shard.project_name
    suite_dir = run_dir_base / task.test_type / task.suite_dir.name
    suite_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("node-logs", "core-dumps", "stack-traces", "health-logs", "reports", "scenario-logs"):
        (suite_dir / sub).mkdir(exist_ok=True)

    MonitoringManager.get_instance(
        node_cli_path="cellframe-node-cli",
        log_file=suite_dir,
        shard_key=shard_key,
    )

    paths_config = config_loader.get_paths_config()
    project_root = (base_path / paths_config.get("project_root", "../..")).resolve()
    common_root = find_common_root(
        task.suite_dir, fallback=base_path / "tests"
    )
    fallback_common = (base_path / "tests" / "integration" / "scenarios").resolve()
    if not fallback_common.exists():
        fallback_common = None

    custom_tpl_raw = paths_config.get("custom_templates_dir", "")
    custom_templates_dirs = []
    if custom_tpl_raw:
        resolved = (project_root / custom_tpl_raw).resolve()
        if resolved.is_dir():
            custom_templates_dirs.append(resolved)

    # Parse suite descriptor
    parser = ScenarioParser(
        scenarios_root=task.descriptor_path.parent,
        common_root=common_root,
        fallback_common_root=fallback_common,
    )
    suite_desc_rel = task.descriptor_path.relative_to(task.descriptor_path.parent)
    suite_spec = parser.load_scenario(str(suite_desc_rel))
    suite_name = suite_spec.name if hasattr(suite_spec, "name") else task.suite_dir.name

    async def _start():
        await network_mgr.start(rebuild=False, wait_ready=True)

    try:
        asyncio.run(_start())
    except Exception as start_exc:
        # Collect node logs even when shard startup fails so we can diagnose why
        _collect_shard_logs_on_failure(shard, suite_dir)
        raise

    # Provision suite services (node_compose, docker_compose, generators, etc.)
    from ..cli.test_commands import provision_suite_services
    topology_vars, suite_env = provision_suite_services(
        suite_spec, network_mgr, task.suite_dir, base_path,
        common_root, fallback_common, config_loader,
        suite_variables=None, project_root=project_root,
    )
    if cli_params:
        topology_vars.update(cli_params)

    # Suite setup (YAML-level setup steps)
    suite_setup_variables: Dict[str, str] = {}
    if isinstance(suite_spec, SuiteDescriptor) and (suite_spec.includes or suite_spec.setup):
        suite_setup_parser = SuiteSetupParser(
            scenarios_root=task.suite_dir,
            common_root=common_root,
            fallback_common_root=fallback_common,
        )
        suite_setup_scenario = suite_setup_parser.load_suite_setup(
            suite_includes=suite_spec.includes or [],
            suite_setup=suite_spec.setup.model_dump() if suite_spec.setup else None,
            suite_name=suite_name,
            base_dir=task.descriptor_path.parent,
        )
        executor = ScenarioExecutor(
            node_cli_path="cellframe-node-cli",
            log_file=suite_dir / "suite-setup.log",
            debug=debug_mode,
            base_path=base_path,
            custom_templates_dirs=custom_templates_dirs,
            cache_dir=shard_cache,
        )
        executor.load_operands(
            common_root / "operands",
            common_root / "common" / "operands",
            common_root / "scenarios" / "common" / "operands",
        )

        setup_vars = dict(topology_vars)
        if isinstance(suite_spec, SuiteDescriptor) and suite_spec.variables:
            setup_vars.update(suite_spec.variables)

        async def _run_setup():
            return await executor.execute_scenario(
                suite_setup_scenario,
                compose_manager=network_mgr.compose,
                snapshot_manager=network_mgr.snapshot_manager,
                initial_variables=setup_vars or None,
            )

        setup_ctx = asyncio.run(_run_setup())
        suite_setup_variables = dict(setup_ctx.variables)

    # Run scenarios
    scenario_parser = ScenarioParser(
        scenarios_root=task.suite_dir,
        common_root=common_root,
        fallback_common_root=fallback_common,
    )

    for scenario_file in task.scenario_files:
        result.total += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        scenario_log = suite_dir / "scenario-logs" / f"scenario_{scenario_file.stem}_{timestamp}.log"

        try:
            relative_path = scenario_file.relative_to(task.suite_dir)
            scenario = scenario_parser.load_scenario(str(relative_path))
            if isinstance(scenario, SuiteDescriptor):
                result.total -= 1
                continue

            if isinstance(suite_spec, SuiteDescriptor) and suite_spec.variables:
                merged = dict(suite_spec.variables)
                merged.update(scenario.variables)
                scenario.variables = merged

            executor = ScenarioExecutor(
                node_cli_path="cellframe-node-cli",
                log_file=scenario_log,
                debug=debug_mode,
                base_path=base_path,
                custom_templates_dirs=custom_templates_dirs,
                cache_dir=shard_cache,
            )
            executor.load_operands(
                common_root / "operands",
                common_root / "common" / "operands",
                common_root / "scenarios" / "common" / "operands",
            )

            init_vars = dict(topology_vars)
            if suite_setup_variables:
                init_vars.update(suite_setup_variables)

            async def _run():
                return await executor.execute_scenario(
                    scenario,
                    compose_manager=network_mgr.compose,
                    snapshot_manager=network_mgr.snapshot_manager,
                    initial_variables=init_vars or None,
                )

            ctx = asyncio.run(_run())
            summary = ctx.get_summary()
            result.passed += 1
            result.scenario_results.append({
                "name": scenario.name,
                "file": scenario_file.name,
                "suite": suite_name,
                "status": "passed",
                "duration": summary.get("duration_seconds", 0),
                "steps_total": summary["total_steps"],
                "steps_passed": summary["passed"],
            })

        except ScenarioExecutionError as e:
            result.failed += 1
            result.scenario_results.append({
                "name": scenario_file.stem,
                "file": scenario_file.name,
                "suite": suite_name,
                "status": "failed",
                "error": str(e),
            })
        except Exception as e:
            result.failed += 1
            result.scenario_results.append({
                "name": scenario_file.stem,
                "file": scenario_file.name,
                "suite": suite_name,
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc(),
            })

    # Collect Docker container logs before stopping
    try:
        import docker as docker_sdk
        client = docker_sdk.from_env()
        containers = client.containers.list(
            all=True,
            filters={"label": f"com.docker.compose.project={shard.project_name}"},
        )
        node_logs_dir = suite_dir / "node-logs"
        for container in containers:
            try:
                svc_name = container.labels.get("com.docker.compose.service", "")
                if svc_name:
                    logs = container.logs(tail=50000).decode('utf-8', errors='ignore')
                    (node_logs_dir / f"{svc_name}.log").write_text(logs)
            except Exception:
                pass
    except Exception:
        pass

    # Stop shard network
    async def _stop():
        await network_mgr.stop(remove_volumes=False)

    try:
        asyncio.run(_stop())
    except Exception:
        pass

    MonitoringManager.reset_instance(shard_key=shard_key)


def _cleanup_shard(shard, base_path: Path) -> None:
    """Best-effort cleanup of shard Docker resources and disk data."""
    try:
        import docker
        client = docker.from_env(timeout=30)
        containers = client.containers.list(
            all=True,
            filters={"label": f"com.docker.compose.project={shard.project_name}"},
        )
        for c in containers:
            try:
                c.remove(force=True)
            except Exception:
                pass

        for net in client.networks.list(names=[f"{shard.project_name}_"]):
            try:
                net.remove()
            except Exception:
                pass
    except Exception:
        pass

    shard_cache = (base_path / shard.cache_dir).resolve()
    if shard_cache.exists():
        _remove_shard_data(shard_cache)


def _remove_shard_data(shard_cache: Path) -> None:
    """Remove shard cache data, using Docker for root-owned files if needed."""
    import shutil
    try:
        shutil.rmtree(shard_cache)
    except PermissionError:
        import subprocess
        subprocess.run(
            ["docker", "run", "--rm",
             "-v", f"{shard_cache.parent}:/cleanup",
             "alpine", "sh", "-c",
             f"rm -rf /cleanup/{shard_cache.name}"],
            timeout=30, capture_output=True,
        )
    except Exception:
        pass


def _collect_shard_logs_on_failure(shard, suite_dir: Path) -> None:
    """Collect container logs when a shard fails to start (best-effort)."""
    try:
        import docker as docker_sdk
        client = docker_sdk.from_env()
        containers = client.containers.list(
            all=True,
            filters={"label": f"com.docker.compose.project={shard.project_name}"},
        )
        node_logs_dir = suite_dir / "node-logs"
        node_logs_dir.mkdir(parents=True, exist_ok=True)
        for container in containers:
            try:
                svc_name = container.labels.get("com.docker.compose.service", "")
                if svc_name:
                    logs = container.logs(tail=50000).decode('utf-8', errors='ignore')
                    (node_logs_dir / f"{svc_name}.log").write_text(logs)
            except Exception:
                pass
    except Exception:
        pass
