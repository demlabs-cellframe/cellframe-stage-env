"""
CLI commands for running tests.

This module contains the main test execution command extracted from stage_env.py.
"""
import asyncio
import typer
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Callable

from .common import print_info, print_success, print_error, print_warning


def _provision_node_compose(network_mgr, node_compose, base_path, config_loader, print_info, print_success, print_warning, print_error, suite_variables=None):
    """
    Provision additional cellframe nodes declared in suite.node_compose.

    New nodes are registered in ``network_mgr.nodes`` (the single source of
    truth) and receive IDs that follow the existing base-topology nodes.

    Args:
        node_compose: Dict[str, NodeComposeSpec] — keys are service names
    """
    import ipaddress
    import re
    import shutil
    _asan_ignore = shutil.ignore_patterns("asan.*")

    from ..network.models import NodeConfig

    settings = network_mgr.topology.network_settings
    base_ip = ipaddress.ip_address(settings.base_ip)

    cache_dir = Path(config_loader.get_paths_config().get('cache_dir', '../../cache'))
    if not cache_dir.is_absolute():
        cache_dir = (base_path / cache_dir).resolve()

    max_existing_id = max(
        (cfg.node_id for cfg in network_mgr.nodes.values()), default=0
    )
    next_auto_id = max_existing_id + 1

    compose_specs: list[dict] = []
    packages_to_install: dict[str, list[str]] = {}

    for svc_name, spec in node_compose.items():
        node_id = spec.id if spec.id is not None else next_auto_id
        next_auto_id = max(next_auto_id, node_id) + 1

        ip_addr = str(base_ip + node_id - 1)
        http_port = settings.base_http_port + (node_id - 1)

        node_cfg = NodeConfig(
            node_id=node_id,
            role=spec.role,
            node_type=spec.role,
            rpc_port=settings.base_rpc_port + (node_id - 1),
            p2p_port=settings.base_p2p_port + (node_id - 1),
            cf_port=settings.base_cf_port + (node_id - 1),
            http_port=http_port,
            ip_address=ip_addr,
        )
        network_mgr.nodes[svc_name] = node_cfg

        compose_specs.append({
            'id': node_id,
            'service_name': svc_name,
            'role': spec.role,
            'ip_address': ip_addr,
            'http_port': http_port,
        })

        cfg_dir = cache_dir / "configs" / f"node{node_id}"
        data_dir = cache_dir / "data" / f"node{node_id}"
        source = spec.source.strip().lower()

        if source == "genesis":
            src_node = _find_donor_node(cache_dir, "configs")
            if src_node and not cfg_dir.exists():
                shutil.copytree(cache_dir / "configs" / src_node, cfg_dir, dirs_exist_ok=True, ignore=_asan_ignore)
                print_info(f"    configs from genesis ({src_node})")
            if src_node and not data_dir.exists():
                src_data = cache_dir / "data" / src_node
                if src_data.exists():
                    shutil.copytree(src_data, data_dir, dirs_exist_ok=True, ignore=_asan_ignore)
        elif source.startswith("node-"):
            clone_m = re.match(r'node-(\d+)', source)
            if not clone_m:
                print_warning(f"  [{svc_name}] bad source '{source}'")
                continue
            clone_id = clone_m.group(1)
            src_cfg = cache_dir / "configs" / f"node{clone_id}"
            src_data = cache_dir / "data" / f"node{clone_id}"
            if src_cfg.exists() and not cfg_dir.exists():
                shutil.copytree(src_cfg, cfg_dir, dirs_exist_ok=True, ignore=_asan_ignore)
            if src_data.exists() and not data_dir.exists():
                shutil.copytree(src_data, data_dir, dirs_exist_ok=True, ignore=_asan_ignore)
        elif source == "fresh":
            cfg_dir.mkdir(parents=True, exist_ok=True)
            (cfg_dir / "cellframe-node.cfg.d").mkdir(exist_ok=True)
            (cfg_dir / "network").mkdir(exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)
            donor = _find_donor_node(cache_dir, "configs")
            if donor and not (cfg_dir / "cellframe-node.cfg").exists():
                shutil.copy2(cache_dir / "configs" / donor / "cellframe-node.cfg", cfg_dir / "cellframe-node.cfg")
        else:
            print_warning(f"  [{svc_name}] unknown source '{source}', using fresh")
            cfg_dir.mkdir(parents=True, exist_ok=True)
            data_dir.mkdir(parents=True, exist_ok=True)

        (cache_dir / "crash-artifacts" / f"node{node_id}").mkdir(parents=True, exist_ok=True)

        # MDBX lock files copied from donor become stale in 5.x; remove to allow writes
        _stage_cfg = config_loader.load_stage_config()
        _gver = _stage_cfg.get('genesis_version', '')
        if not _gver.startswith('v6'):
            for lck in data_dir.rglob("mdbx.lck"):
                lck.unlink(missing_ok=True)

        if spec.regenerate_cert:
            import glob as _glob
            ca_dir = data_dir / "lib" / "ca"
            if ca_dir.is_dir():
                for cert_file in _glob.glob(str(ca_dir / "node-addr*")):
                    Path(cert_file).unlink(missing_ok=True)
                print_info(f"    regenerate_cert: removed node-addr certs for {svc_name}")

        if spec.config_overrides:
            cfg_d = cfg_dir / "cellframe-node.cfg.d"
            cfg_d.mkdir(parents=True, exist_ok=True)
            lines = [f"# Auto-generated config overrides for {svc_name}"]

            def _cfg_val(v):
                if isinstance(v, bool):
                    return "true" if v else "false"
                s = str(v)
                import re as _r
                return _r.sub(
                    r'\{\{(\w+)\}\}',
                    lambda m: str(override_vars.get(m.group(1), m.group(0))),
                    s,
                )

            override_vars = {
                'network_name': network_mgr.topology.network.name,
                **(suite_variables or {}),
            }

            for section, values in spec.config_overrides.items():
                lines.append(f"\n[{section}]")
                if isinstance(values, dict):
                    for k, v in values.items():
                        lines.append(f"{k}={_cfg_val(v)}")
                else:
                    lines.append(str(values))
            (cfg_d / "suite-overrides.cfg").write_text("\n".join(lines) + "\n")
            print_info(f"    config_overrides: {list(spec.config_overrides.keys())}")

        if spec.packages:
            packages_to_install[svc_name] = spec.packages.split()

        print_info(f"  {svc_name}  id={node_id} role={spec.role} {ip_addr}:{http_port}")

    if not compose_specs:
        return

    stage_config = config_loader.load_stage_config()
    try:
        network_mgr.compose.add_extra_node_services(
            compose_specs,
            network_settings=stage_config,
            cache_dir_relative=str(Path(config_loader.get_paths_config().get('cache_dir', '../../cache'))),
        )
        svc_names = [s['service_name'] for s in compose_specs]
        network_mgr.compose.up(services=svc_names, detach=True, wait=False, no_build=True)
        print_success(f"  Started: {', '.join(svc_names)}")
    except Exception as e:
        print_error(f"  Failed to provision node_compose: {e}")
        return

    for svc_name, pkgs in packages_to_install.items():
        pkg_str = " ".join(pkgs)
        try:
            exit_code, output = network_mgr.compose.exec(
                svc_name, ["bash", "-c", f"apt-get update -qq && apt-get install -y -qq {pkg_str} && rm -rf /var/lib/apt/lists/*"]
            )
            if exit_code != 0:
                print_warning(f"  [{svc_name}] package install failed: {output[:200]}")
            else:
                print_info(f"  [{svc_name}] installed: {pkg_str}")
        except Exception as e:
            print_warning(f"  [{svc_name}] package install error: {e}")


def _find_donor_node(cache_dir: Path, subdir: str) -> Optional[str]:
    """Find first existing node directory (e.g. 'node1') in cache_dir/subdir."""
    import os
    target = cache_dir / subdir
    if not target.exists():
        return None
    for d in sorted(os.listdir(target)):
        if d.startswith("node") and (target / d / "cellframe-node.cfg").exists():
            return d
    return None


def register_commands(app: typer.Typer, base_path: Path, get_config_path: Callable[[], Optional[Path]]):
    """Register test execution commands."""
    
    @app.command()
    def run_tests(
        test_dirs: List[str] = typer.Argument(..., help="Test scenario directories to run"),
        parallel: bool = typer.Option(False, "--parallel", "-p", help="Run tests in parallel (not yet implemented)"),
        filter: Optional[str] = typer.Option(None, "--filter", "-k", help="Filter tests by pattern"),
        start_network: bool = typer.Option(True, "--start-network/--no-start-network", help="Start network before tests"),
        stop_after: bool = typer.Option(True, "--stop-after/--keep-running", help="Stop network after tests"),
    ):
        """🧪 Run YAML test scenarios from specified directories."""
        
        from ..scenarios.parser import ScenarioParser
        from ..scenarios.executor import ScenarioExecutor, ScenarioExecutionError
        from ..scenarios.schema import SuiteDescriptor
        from src.utils.artifacts import ArtifactsManager
        from ..config.manager import get_config_loader
        from ..network.manager import NetworkManager
        from ..monitoring.manager import MonitoringManager
        from src.utils.report_generator import ReportGenerator
        from ..scenarios.extractors import set_debug_mode
        import docker
        from src.utils.logger import logger
        
        print_info(f"Running tests from {len(test_dirs)} director{'y' if len(test_dirs) == 1 else 'ies'}:")
        for test_dir in test_dirs:
            print_info(f"  • {test_dir}")
        
        # Load configuration
        config_loader = get_config_loader()
        artifacts_config = config_loader.get_artifacts_config()
        artifacts_manager = ArtifactsManager(base_path, artifacts_config)
        
        # Load scenarios config and set debug mode
        scenarios_config = config_loader.get_scenarios_config()
        debug_mode = scenarios_config.get('debug', False)
        set_debug_mode(debug_mode)
        
        if debug_mode:
            print_info("🐛 Debug mode enabled for scenario extraction")
        
        # Create run ID - one timestamp for entire test session
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        run_id = timestamp_str
        
        # Create base run directory
        run_dir_base = artifacts_manager.artifacts_root / f"run_{run_id}"
        run_dir_base.mkdir(parents=True, exist_ok=True)
        
        print_info(f"📁 Created run directory: run_{run_id}/")
        
        # Start network if requested
        network_mgr = None
        if start_network:
            print_info("\n🚀 Starting test network...")
            config_path = get_config_path()
            network_mgr = NetworkManager(base_path, topology_name="default", config_path=config_path)
            # Pass keep_running flag to prevent network shutdown on errors
            network_mgr.keep_running = not stop_after
            
            async def _start_network():
                await network_mgr.start(rebuild=False, wait_ready=True)
            
            try:
                asyncio.run(_start_network())
                print_success("Network started successfully")
                
                # Initialize CLI parser with help data from node
                print_info("📖 Parsing CLI commands...")
                from src.utils.cli_parser import get_cli_parser
                
                cache_file = base_path / "cache" / "cli_commands.json"
                cli_parser = get_cli_parser(cache_file=cache_file)
                
                # Parse CLI help from first node container
                async def _init_cli_parser():
                    # Use node1 container for parsing
                    container_name = "cellframe-stage-node-1"
                    success = await cli_parser.parse_cli_help(container_name, use_cache=True)
                    return success
                
                parser_success = asyncio.run(_init_cli_parser())
                if parser_success:
                    stats = cli_parser.get_stats()
                    print_success(f"✓ CLI parser initialized: {stats['total_commands']} commands")
                else:
                    print_warning("⚠️  CLI parser initialization failed - defaults will not be applied")
            except Exception as e:
                print_error(f"Failed to start network: {e}")
                raise typer.Exit(1)
        else:
            # Network already running - connect to it
            print_info("🔗 Connecting to running network...")
            config_path = get_config_path()
            network_mgr = NetworkManager(base_path, topology_name="default", config_path=config_path)
            network_mgr.keep_running = not stop_after

            # Point compose manager to generated file if it exists
            generated = network_mgr.compose.project_dir / "docker-compose.generated.yml"
            if generated.exists():
                network_mgr.compose.compose_file = generated
            
            # Still need to initialize CLI parser
            print_info("📖 Initializing CLI parser from running network...")
            from src.utils.cli_parser import get_cli_parser
            
            cache_file = base_path / "cache" / "cli_commands.json"
            cli_parser = get_cli_parser(cache_file=cache_file)
            
            async def _init_cli_parser():
                container_name = "cellframe-stage-node-1"
                success = await cli_parser.parse_cli_help(container_name, use_cache=True)
                return success
            
            try:
                parser_success = asyncio.run(_init_cli_parser())
                if parser_success:
                    stats = cli_parser.get_stats()
                    print_success(f"✓ CLI parser initialized: {stats['total_commands']} commands")
                else:
                    print_warning("⚠️  CLI parser initialization failed - defaults will not be applied")
            except Exception as e:
                print_warning(f"CLI parser init failed: {e}")
        
        all_passed = True
        total_scenarios = 0
        passed_scenarios = 0
        failed_scenarios = 0
        scenario_results = []
        
        cli_path = "cellframe-node-cli"
        
        # Check if we have pristine network (just started with snapshot)
        pristine_marker = artifacts_manager.artifacts_root / ".pristine_network"
        is_first_suite = pristine_marker.exists()
        
        if is_first_suite:
            print_info("🎯 Detected pristine network - first suite will use it directly!")
        
        # Track if this is the first suite (to optimize snapshot creation)
        first_suite_executed = False
        snapshot_created = False
        
        # Initialize monitoring services ONCE for entire test session
        try:
            MonitoringManager.get_instance(
                node_cli_path=cli_path,
                log_file=run_dir_base
            )
            print_info("🔍 Monitoring services initialized")
        except Exception as e:
            print_warning(f"Failed to initialize monitoring: {e}")
        
        # Main test execution loop
        try:
            for test_dir in test_dirs:
                test_path = Path(test_dir).resolve()
                
                if not test_path.exists():
                    print_warning(f"Directory not found: {test_path}")
                    continue
                
                # Find all YAML scenario files
                yml_files = list(test_path.glob("**/*.yml")) + list(test_path.glob("**/*.yaml"))
                
                if not yml_files:
                    print_warning(f"No YAML scenario files found in {test_path.name}")
                    continue
                
                # Group files by suite
                suites = {}
                standalone_scenarios = []
                
                for yml_file in yml_files:
                    parent_dir = yml_file.parent
                    file_stem = yml_file.stem
                    
                    # Pattern A: External descriptor (parent/name.yml + parent/name/)
                    matching_dir = parent_dir / file_stem
                    if matching_dir.exists() and matching_dir.is_dir():
                        suite_key = str(matching_dir.relative_to(test_path))
                        if suite_key not in suites:
                            suites[suite_key] = {
                                'descriptor': yml_file,
                                'scenarios': [],
                                'path': matching_dir
                            }
                        continue
                    
                    # Pattern B: Internal descriptor (dir/suite.yml)
                    if file_stem == 'suite':
                        suite_key = str(parent_dir.relative_to(test_path))
                        if suite_key not in suites:
                            suites[suite_key] = {
                                'descriptor': yml_file,
                                'scenarios': [],
                                'path': parent_dir
                            }
                        continue
                    
                    # Check if this scenario belongs to a suite
                    suite_found = False
                    for potential_suite_dir in [parent_dir] + list(parent_dir.parents):
                        if potential_suite_dir == test_path:
                            break
                        suite_name = potential_suite_dir.name
                        # Check external descriptor (parent/name.yml)
                        external_descriptor = potential_suite_dir.parent / f"{suite_name}.yml"
                        # Check internal descriptor (dir/suite.yml)
                        internal_descriptor = potential_suite_dir / "suite.yml"
                        descriptor_file = None
                        if external_descriptor.exists():
                            descriptor_file = external_descriptor
                        elif internal_descriptor.exists():
                            descriptor_file = internal_descriptor
                        if descriptor_file:
                            suite_key = str(potential_suite_dir.relative_to(test_path))
                            if suite_key not in suites:
                                suites[suite_key] = {
                                    'descriptor': descriptor_file,
                                    'scenarios': [],
                                    'path': potential_suite_dir
                                }
                            suites[suite_key]['scenarios'].append(yml_file)
                            suite_found = True
                            break
                    
                    if not suite_found:
                        standalone_scenarios.append(yml_file)
                
                # Process each suite
                for suite_key, suite_info in suites.items():
                    suite_path = suite_info['path']
                    suite_descriptor = suite_info['descriptor']
                    suite_scenarios = suite_info['scenarios']
                    
                    # Parse suite descriptor to get metadata
                    # common_root: use project's tests/e2e/ for cross-suite common includes
                    paths_config = get_config_loader().get_paths_config()
                    project_root = (base_path / paths_config.get('project_root', '../..')).resolve()
                    common_root = project_root / "tests" / "e2e"
                    if not common_root.exists():
                        common_root = base_path / "tests"

                    custom_tpl_raw = paths_config.get('custom_templates_dir', '')
                    custom_templates_dirs = []
                    if custom_tpl_raw:
                        resolved = (project_root / custom_tpl_raw).resolve()
                        if resolved.is_dir():
                            custom_templates_dirs.append(resolved)

                    parser = ScenarioParser(scenarios_root=suite_descriptor.parent, common_root=common_root)
                    
                    suite_spec = None  # Initialize to None in case of parse failure
                    try:
                        suite_desc_rel = suite_descriptor.relative_to(suite_descriptor.parent)
                        suite_spec = parser.load_scenario(str(suite_desc_rel))
                        if isinstance(suite_spec, SuiteDescriptor):
                            suite_name = suite_spec.name
                            suite_description = suite_spec.description
                        else:
                            suite_name = suite_spec.name
                            suite_description = getattr(suite_spec, 'description', None)
                    except Exception as e:
                        suite_name = suite_path.name
                        suite_description = None
                        print_warning(f"Failed to parse suite descriptor {suite_descriptor.name}: {e}")
                    
                    # Create suite-specific directory
                    test_type = test_path.name
                    suite_relative_path = Path(test_type) / suite_path.name
                    suite_dir = run_dir_base / suite_relative_path
                    suite_dir.mkdir(parents=True, exist_ok=True)
                    
                    # Create artifact subdirectories
                    for subdir in ["node-logs", "core-dumps", "stack-traces", "health-logs", "reports", "scenario-logs"]:
                        (suite_dir / subdir).mkdir(exist_ok=True)
                    
                    print_info(f"\n{'═' * 60}")
                    print_info(f"📦 Suite: {suite_name}")
                    if suite_description:
                        print_info(f"   {suite_description}")
                    print_info(f"   Path: {suite_relative_path}")
                    print_info(f"   Scenarios: {len(suite_scenarios)}")
                    print_info(f"{'═' * 60}")
                    
                    # Clean test data before each suite (if network is running)
                    if network_mgr:
                        restore_snapshot_name = None
                        if isinstance(suite_spec, SuiteDescriptor) and suite_spec.restore_snapshot:
                            restore_snapshot_name = suite_spec.restore_snapshot
                            if "{{topology_name}}" in restore_snapshot_name:
                                topology_name = getattr(suite_spec.network, 'topology', 'default') if suite_spec.network else 'default'
                                restore_snapshot_name = restore_snapshot_name.replace("{{topology_name}}", topology_name)
                        
                        if is_first_suite:
                            try:
                                pristine_marker.unlink()
                            except FileNotFoundError:
                                pass
                            is_first_suite = False
                            print_success("🚀 Using pristine network (no restore needed)")
                        else:
                            if restore_snapshot_name:
                                print_info(f"🔄 Restoring from snapshot: {restore_snapshot_name}")
                            else:
                                print_info("🧹 Restoring clean environment state...")
                            
                            async def _restore_state():
                                await network_mgr.restore_clean_state(name=restore_snapshot_name)
                            
                            try:
                                asyncio.run(_restore_state())
                                print_success(f"✓ Environment restored from snapshot{': ' + restore_snapshot_name if restore_snapshot_name else ''}")
                            except Exception as e:
                                print_warning(f"Failed to restore state: {e}")

                    # Populate base-topology node registry so that
                    # docker_compose and node_compose blocks can reference
                    # existing nodes and allocate non-conflicting IDs.
                    if network_mgr and not network_mgr.nodes:
                        network_mgr.generate_node_configs()

                    # Propagate docker_compose services to network manager.
                    # Strip 'packages' field — it's our extension, not docker-compose.
                    node_packages: list[str] = []
                    if network_mgr and isinstance(suite_spec, SuiteDescriptor) and suite_spec.docker_compose:
                        clean_services: dict = {}
                        for svc_name, svc_def in suite_spec.docker_compose.items():
                            svc_copy = dict(svc_def) if isinstance(svc_def, dict) else svc_def
                            pkg_str = svc_copy.pop("packages", None)
                            if pkg_str:
                                node_packages.extend(pkg_str.split())
                            clean_services[svc_name] = svc_copy
                        network_mgr.docker_compose = clean_services
                        print_info(f"🐳 Docker compose services: {', '.join(clean_services.keys())}")

                        if node_packages:
                            pkgs = " ".join(sorted(set(node_packages)))
                            print_info(f"📦 Installing packages on nodes: {pkgs}")
                            node_svc_names = [f"node-{c.node_id}" for c in sorted(network_mgr.nodes.values(), key=lambda c: c.node_id)]
                            install_cmd = ["bash", "-c", f"apt-get update -qq && apt-get install -y -qq {pkgs} && rm -rf /var/lib/apt/lists/*"]
                            for svc in node_svc_names:
                                try:
                                    exit_code, output = network_mgr.compose.exec(svc, install_cmd)
                                    if exit_code != 0:
                                        print_warning(f"  Package install on {svc} failed (exit {exit_code}): {output[:200]}")
                                except Exception as e:
                                    print_warning(f"  Package install on {svc}: {e}")
                            print_success(f"✓ Packages installed: {pkgs}")

                    # Merge includes in declared order: variables, node_compose, node_compose_gen.
                    # Entries can be file paths (str) or inline data blocks (dict).
                    if network_mgr and isinstance(suite_spec, SuiteDescriptor) and suite_spec.includes:
                        import yaml as _yaml
                        from ..scenarios.schema import NodeComposeSpec, NodeComposeGenSpec

                        def _merge_inc_data(inc_data: dict) -> None:
                            inc_vars = inc_data.get("variables")
                            if inc_vars and isinstance(inc_vars, dict):
                                merged = dict(inc_vars)
                                merged.update(suite_spec.variables)
                                suite_spec.variables = merged
                            nc_raw = inc_data.get("node_compose")
                            if nc_raw and isinstance(nc_raw, dict):
                                for k, v in nc_raw.items():
                                    if k not in suite_spec.node_compose:
                                        suite_spec.node_compose[k] = NodeComposeSpec(**(v if isinstance(v, dict) else {}))
                            ncg_raw = inc_data.get("node_compose_gen")
                            if ncg_raw and isinstance(ncg_raw, list):
                                for entry in ncg_raw:
                                    suite_spec.node_compose_gen.append(
                                        NodeComposeGenSpec(**(entry if isinstance(entry, dict) else {}))
                                    )

                        for inc_entry in suite_spec.includes:
                            if isinstance(inc_entry, dict):
                                _merge_inc_data(inc_entry)
                                continue
                            for search_dir in [suite_path, common_root]:
                                inc_full = (search_dir / inc_entry).resolve()
                                if inc_full.exists():
                                    with open(inc_full) as _f:
                                        inc_data = _yaml.safe_load(_f) or {}
                                    _merge_inc_data(inc_data)
                                    break

                    # Expand node_compose_gen → node_compose (resolve {{var}} in count)
                    if isinstance(suite_spec, SuiteDescriptor) and suite_spec.node_compose_gen:
                        import re as _re
                        from ..scenarios.schema import NodeComposeSpec
                        variables = suite_spec.variables or {}
                        for gen in suite_spec.node_compose_gen:
                            count = gen.count
                            if isinstance(count, str):
                                resolved = _re.sub(
                                    r'\{\{(\w+)\}\}',
                                    lambda m: str(variables.get(m.group(1), m.group(0))),
                                    count,
                                )
                                try:
                                    count = int(resolved)
                                except ValueError:
                                    print_warning(f"  node_compose_gen '{gen.prefix}': cannot resolve count '{count}'")
                                    continue
                            for i in range(1, count + 1):
                                svc_name = f"{gen.prefix}-{i}"
                                if svc_name not in suite_spec.node_compose:
                                    suite_spec.node_compose[svc_name] = NodeComposeSpec(
                                        role=gen.role,
                                        source=gen.source,
                                        packages=gen.packages,
                                        config_overrides=gen.config_overrides,
                                        setup=gen.setup,
                                        regenerate_cert=gen.regenerate_cert,
                                    )

                    # Provision additional cellframe nodes from suite descriptor
                    if network_mgr and isinstance(suite_spec, SuiteDescriptor) and suite_spec.node_compose:
                        print_info("🖥️ Provisioning node_compose nodes...")
                        _provision_node_compose(
                            network_mgr, suite_spec.node_compose, base_path,
                            config_loader, print_info, print_success, print_warning, print_error,
                            suite_variables=suite_spec.variables,
                        )
                        # Install docker_compose packages on node_compose nodes too
                        if node_packages:
                            pkgs = " ".join(sorted(set(node_packages)))
                            nc_svc_names = list(suite_spec.node_compose.keys())
                            install_cmd = ["bash", "-c", f"apt-get update -qq && apt-get install -y -qq {pkgs} && rm -rf /var/lib/apt/lists/*"]
                            for svc in nc_svc_names:
                                try:
                                    exit_code, output = network_mgr.compose.exec(svc, install_cmd)
                                    if exit_code != 0:
                                        print_warning(f"  Package install on {svc} failed (exit {exit_code}): {output[:200]}")
                                except Exception as e:
                                    print_warning(f"  Package install on {svc}: {e}")

                    topology_vars = {}
                    if network_mgr:
                        from ..scenarios.global_context import ScenarioGlobalContext
                        gc = ScenarioGlobalContext(
                            network_name=network_mgr.topology.network.name,
                            topology_name=network_mgr.topology_name,
                            native_ticker=getattr(network_mgr.topology.network, 'native_ticker', 'TCELL'),
                            node_port=getattr(network_mgr.topology.network_settings, 'node_port', 8079)
                        )
                        node_configs_for_setup = network_mgr.generate_node_configs()
                        gc.set_static_node_info(node_configs_for_setup)
                        gc.collect_node_ips(node_configs_for_setup, wait_for_ips=False)
                        topology_vars = gc.to_dict()
                        topology_vars['project_root'] = str(project_root)

                    # Execute suite-level setup (includes + setup steps).
                    # Includes always run — each include decides internally whether
                    # to act (e.g. by checking snapshot: verify) or skip.
                    if isinstance(suite_spec, SuiteDescriptor) and (suite_spec.includes or suite_spec.setup):
                        print_info("🔧 Executing suite-level setup...")
                        
                        from ..scenarios.executor import ScenarioExecutor
                        from ..scenarios.parser import SuiteSetupParser
                        
                        try:
                            suite_setup_parser = SuiteSetupParser(
                                scenarios_root=suite_path,
                                common_root=common_root
                            )
                            
                            suite_setup_scenario = suite_setup_parser.load_suite_setup(
                                suite_includes=suite_spec.includes or [],
                                suite_setup=suite_spec.setup.model_dump() if suite_spec.setup else None,
                                suite_name=suite_name,
                                base_dir=suite_path
                            )
                            
                            executor = ScenarioExecutor(
                                node_cli_path="cellframe-node-cli",
                                log_file=suite_dir / "suite-setup.log",
                                debug=debug_mode,
                                base_path=base_path,
                                custom_templates_dirs=custom_templates_dirs,
                            )
                            executor.load_operands(common_root / "operands", common_root / "common" / "operands", common_root / "scenarios" / "common" / "operands")

                            setup_vars = dict(topology_vars or {})
                            if isinstance(suite_spec, SuiteDescriptor) and suite_spec.variables:
                                setup_vars.update(suite_spec.variables)

                            async def _run_suite_setup():
                                await executor.execute_scenario(
                                    suite_setup_scenario,
                                    compose_manager=network_mgr.compose if network_mgr else None,
                                    snapshot_manager=network_mgr.snapshot_manager if network_mgr else None,
                                    initial_variables=setup_vars or None
                                )
                            
                            asyncio.run(_run_suite_setup())
                            print_success("✓ Suite setup completed")
                            
                        except Exception as e:
                            all_passed = False
                            print_error(f"Suite setup failed: {e}")
                            print_error(f"❌ Skipping all scenarios in suite: {suite_name}")
                            continue


                    
                    # Order scenarios according to suite descriptor if specified
                    if isinstance(suite_spec, SuiteDescriptor) and suite_spec.scenarios:
                        order_map = {}
                        for idx, name in enumerate(suite_spec.scenarios):
                            order_map[name] = idx
                            order_map[Path(name).stem] = idx
                        def _scenario_order_key(path: Path) -> int:
                            if path.name in order_map:
                                return order_map[path.name]
                            if path.stem in order_map:
                                return order_map[path.stem]
                            return len(suite_spec.scenarios)
                        suite_scenarios = sorted(suite_scenarios, key=_scenario_order_key)
                    
                    # Filter scenarios if needed
                    if filter:
                        suite_scenarios = [f for f in suite_scenarios if filter.lower() in f.name.lower()]
                        if not suite_scenarios:
                            print_warning(f"No scenarios match filter '{filter}' in suite {suite_name}")
                            continue
                    
                    # Execute suite scenarios
                    # Create fresh parser for each suite to avoid stale cache
                    parser = ScenarioParser(scenarios_root=suite_path, common_root=common_root)
                    
                    for scenario_file in suite_scenarios:
                        total_scenarios += 1
                        print_info(f"\n{'─' * 60}")
                        print_info(f"▶ Running scenario: {scenario_file.name}")
                        
                        # Create scenario log file
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        scenario_name_clean = scenario_file.stem.replace(' ', '_')
                        scenario_log_name = f"scenario_{scenario_name_clean}_{timestamp}.log"
                        scenario_logs_dir = suite_dir / "scenario-logs"
                        scenario_log_file = scenario_logs_dir / scenario_log_name
                        
                        try:
                            # Parse scenario
                            relative_path = scenario_file.relative_to(suite_path)
                            scenario = parser.load_scenario(str(relative_path))
                            
                            # Skip if it's a SuiteDescriptor
                            if isinstance(scenario, SuiteDescriptor):
                                continue
                            
                            # CRITICAL: Merge suite includes/defaults into scenario
                            # Suite includes provide common settings (like -net stagenet)
                            if isinstance(suite_spec, SuiteDescriptor) and suite_spec.includes:
                                # Load suite includes and extract defaults
                                from ..scenarios.parser import ScenarioParser as SP
                                suite_parser = SP(scenarios_root=suite_path, common_root=common_root)
                                
                                # Process suite includes
                                suite_includes_data = {}
                                for include_entry in suite_spec.includes:
                                    if isinstance(include_entry, dict):
                                        if 'defaults' in include_entry:
                                            if not suite_includes_data.get('defaults'):
                                                suite_includes_data['defaults'] = {}
                                            for key, value in include_entry['defaults'].items():
                                                if key not in suite_includes_data['defaults']:
                                                    suite_includes_data['defaults'][key] = value
                                                elif isinstance(value, dict) and isinstance(suite_includes_data['defaults'][key], dict):
                                                    suite_includes_data['defaults'][key].update(value)
                                        continue

                                    search_paths = [
                                        (suite_path / include_entry).resolve(),
                                        (base_path / "tests" / include_entry).resolve(),
                                        (common_root / include_entry).resolve(),
                                    ]
                                    
                                    include_full = None
                                    for path in search_paths:
                                        if path.exists():
                                            include_full = path
                                            break
                                    
                                    if include_full:
                                        with open(include_full, 'r', encoding='utf-8') as f:
                                            import yaml
                                            include_data = yaml.safe_load(f)
                                            if include_data and isinstance(include_data, dict):
                                                if 'defaults' in include_data:
                                                    if not suite_includes_data.get('defaults'):
                                                        suite_includes_data['defaults'] = {}
                                                    for key, value in include_data['defaults'].items():
                                                        if key not in suite_includes_data['defaults']:
                                                            suite_includes_data['defaults'][key] = value
                                                        elif isinstance(value, dict) and isinstance(suite_includes_data['defaults'][key], dict):
                                                            suite_includes_data['defaults'][key].update(value)
                                
                                # Merge suite defaults into scenario defaults
                                if suite_includes_data.get('defaults'):
                                    from ..scenarios.schema import StepDefaults
                                    if not scenario.defaults:
                                        scenario.defaults = StepDefaults()
                                    
                                    suite_defaults_dict = suite_includes_data['defaults']
                                    # Merge cli defaults
                                    if 'cli' in suite_defaults_dict:
                                        if not scenario.defaults.cli:
                                            scenario.defaults.cli = {}
                                        # Add suite CLI defaults that aren't in scenario
                                        for opt, val in suite_defaults_dict['cli'].items():
                                            if opt not in scenario.defaults.cli:
                                                scenario.defaults.cli[opt] = val
                            
                            # Merge suite-level variables into scenario (scenario vars take priority)
                            if isinstance(suite_spec, SuiteDescriptor) and suite_spec.variables:
                                merged_vars = dict(suite_spec.variables)
                                merged_vars.update(scenario.variables)
                                scenario.variables = merged_vars
                            
                            print_info(f"  📋 Name: {scenario.name}")
                            if hasattr(scenario, 'description') and scenario.description:
                                print_info(f"  📝 Description: {scenario.description}")
                            if hasattr(scenario, 'tags') and scenario.tags:
                                print_info(f"  🏷️  Tags: {', '.join(scenario.tags)}")
                            
                            # Get step counts
                            setup_count = len(scenario.setup.steps) if hasattr(scenario.setup, 'steps') else len(scenario.setup or [])
                            test_count = len(scenario.test.steps) if hasattr(scenario.test, 'steps') else len(scenario.test or [])
                            check_count = len(scenario.check.steps) if hasattr(scenario.check, 'steps') else len(scenario.check or [])
                            print_info(f"  📊 Steps: setup={setup_count}, test={test_count}, check={check_count}")
                            print_info(f"  📄 Log: {scenario_log_file.name}")
                            
                            # Setup scenario logging
                            with open(scenario_log_file, 'w', encoding='utf-8') as log_f:
                                log_f.write(f"=== Scenario: {scenario.name} ===\n")
                                log_f.write(f"File: {scenario_file}\n")
                                log_f.write(f"Description: {scenario.description or 'N/A'}\n")
                                log_f.write(f"Tags: {', '.join(scenario.tags) if scenario.tags else 'N/A'}\n")
                                log_f.write(f"Started: {timestamp}\n")
                                log_f.write(f"{'=' * 60}\n\n")
                            
                            # Execute scenario
                            executor = ScenarioExecutor(
                                node_cli_path=cli_path,
                                log_file=scenario_log_file,
                                debug=debug_mode,
                                base_path=base_path,
                                custom_templates_dirs=custom_templates_dirs,
                            )
                            executor.load_operands(common_root / "operands", common_root / "common" / "operands", common_root / "scenarios" / "common" / "operands")

                            async def _execute():
                                return await executor.execute_scenario(
                                    scenario,
                                    compose_manager=network_mgr.compose if network_mgr else None,
                                    snapshot_manager=network_mgr.snapshot_manager if network_mgr else None,
                                    initial_variables=topology_vars or None
                                )
                            
                            print_info("  ▶️  Executing...")
                            ctx = asyncio.run(_execute())
                            
                            # Get summary
                            summary = ctx.get_summary()
                            
                            # Write results to scenario log
                            with open(scenario_log_file, 'a', encoding='utf-8') as log_f:
                                log_f.write(f"\n{'=' * 60}\n")
                                log_f.write(f"=== Results ===\n")
                                log_f.write(f"Status: PASSED\n")
                                log_f.write(f"Steps: {summary['passed']}/{summary['total_steps']} passed\n")
                                if summary.get('variables'):
                                    log_f.write(f"Variables saved: {len(summary['variables'])}\n")
                                    for var_name, var_value in summary.get('variables', {}).items():
                                        log_f.write(f"  {var_name} = {var_value}\n")
                            
                            print_success(f"  ✅ Scenario passed!")
                            print_info(f"     Steps: {summary['passed']}/{summary['total_steps']} passed")
                            if summary.get('variables'):
                                print_info(f"     Variables: {len(summary['variables'])} saved")
                            
                            passed_scenarios += 1
                            
                            result_entry = {
                                'name': scenario.name,
                                'file': scenario_file.name,
                                'suite': suite_name,
                                'path': str(suite_relative_path / scenario_file.name),
                                'status': 'passed',
                                'duration': summary.get('duration_seconds', 0),
                                'steps_total': summary['total_steps'],
                                'steps_passed': summary['passed'],
                                'log_file': str(scenario_log_file.relative_to(run_dir_base))
                            }
                            if summary.get('metrics'):
                                result_entry['metrics'] = summary['metrics']
                            scenario_results.append(result_entry)
                            
                        except ScenarioExecutionError as e:
                            failed_scenarios += 1
                            all_passed = False
                            
                            # Write error to scenario log
                            with open(scenario_log_file, 'a', encoding='utf-8') as log_f:
                                log_f.write(f"\n{'=' * 60}\n")
                                log_f.write(f"=== Results ===\n")
                                log_f.write(f"Status: FAILED\n")
                                log_f.write(f"Error: {str(e)}\n")
                            
                            print_error(f"  ❌ Scenario failed: {str(e)}")
                            logger.error("scenario_execution_failed", scenario=str(scenario_file), error=str(e))
                            
                            # Extract last 30 lines of log
                            error_log_excerpt = ""
                            try:
                                with open(scenario_log_file, 'r', encoding='utf-8') as log_f:
                                    lines = log_f.readlines()
                                    error_log_excerpt = ''.join(lines[-30:])
                            except:
                                error_log_excerpt = "Failed to read log file"
                            
                            # Record failure
                            scenario_results.append({
                                'name': getattr(scenario, 'name', scenario_file.stem),
                                'file': scenario_file.name,
                                'suite': suite_name,
                                'path': str(suite_relative_path / scenario_file.name),
                                'status': 'failed',
                                'error': str(e),
                                'error_log': error_log_excerpt,
                                'log_file': str(scenario_log_file.relative_to(run_dir_base))
                            })
                            
                        except Exception as e:
                            failed_scenarios += 1
                            all_passed = False
                            
                            # Write error to scenario log
                            import traceback
                            with open(scenario_log_file, 'a', encoding='utf-8') as log_f:
                                log_f.write(f"\n{'=' * 60}\n")
                                log_f.write(f"=== Results ===\n")
                                log_f.write(f"Status: ERROR\n")
                                log_f.write(f"Exception: {str(e)}\n")
                                log_f.write(f"Traceback:\n{traceback.format_exc()}\n")
                            
                            print_error(f"  ❌ Unexpected error: {str(e)}")
                            logger.exception("scenario_unexpected_error", scenario=str(scenario_file))
                            
                            # Extract last 30 lines of log
                            error_log_excerpt = ""
                            try:
                                with open(scenario_log_file, 'r', encoding='utf-8') as log_f:
                                    lines = log_f.readlines()
                                    error_log_excerpt = ''.join(lines[-30:])
                            except:
                                error_log_excerpt = "Failed to read log file"
                            
                            # Record error
                            scenario_results.append({
                                'name': scenario_file.stem,
                                'file': scenario_file.name,
                                'suite': suite_name,
                                'path': str(suite_relative_path / scenario_file.name),
                                'status': 'error',
                                'error': f"Unexpected error: {str(e)}",
                                'error_log': error_log_excerpt,
                                'traceback': traceback.format_exc(),
                                'log_file': str(scenario_log_file.relative_to(run_dir_base))
                            })
                    
                    # Collect artifacts for this suite
                    if network_mgr:
                        print_info(f"\n📦 Collecting suite artifacts for {suite_relative_path}...")
                        try:
                            client = docker.from_env()
                            project_name = "cellframe-stage"
                            
                            containers = client.containers.list(
                                all=True,
                                filters={"label": f"com.docker.compose.project={project_name}"}
                            )
                            
                            node_logs_dir = suite_dir / "node-logs"
                            collected_logs = 0
                            
                            for container in containers:
                                try:
                                    container_name = container.name
                                    if "node-" in container_name:
                                        node_name = container_name.split("node-", 1)[1]
                                        node_id = f"node-{node_name}"
                                        
                                        # Collect logs
                                        logs = container.logs(tail=10000).decode('utf-8', errors='ignore')
                                        log_file = node_logs_dir / f"{node_id}.log"
                                        log_file.write_text(logs)
                                        collected_logs += 1
                                except Exception as e:
                                    logger.warning("failed_to_collect_container_log",
                                                    container=container.name,
                                                    error=str(e))
                            
                            if collected_logs > 0:
                                print_success(f"  Collected {collected_logs} node logs")
                            
                            # Collect health logs
                            artifacts_manager.collect_health_logs(suite_dir)
                            print_success(f"  Health logs collected")
                            
                        except Exception as e:
                            print_warning(f"  Failed to collect suite artifacts: {e}")
            
                # Print summary
                print_info(f"\n{'═' * 60}")
                print_info(f"📊 Scenario Test Summary")
                print_info(f"{'═' * 60}")
                print_info(f"Total scenarios: {total_scenarios}")
                if passed_scenarios > 0:
                    print_success(f"✅ Passed: {passed_scenarios}")
                if failed_scenarios > 0:
                    print_error(f"❌ Failed: {failed_scenarios}")
                print_info(f"{'═' * 60}")
                
        finally:
            # Collect final artifacts
            print_info("\n📦 Finalizing artifacts...")
            
            try:
                # Collect stage-env log
                logging_config = config_loader.get_logging_config()
                log_dir_relative = logging_config.get('log_dir', 'logs')
                log_dir = (base_path / log_dir_relative).resolve()
                
                stage_env_logs_dir = run_dir_base / "stage-env-logs"
                stage_env_logs_dir.mkdir(exist_ok=True)
                
                if log_dir.exists():
                    log_files = sorted(log_dir.glob("stage-env_*.log"), 
                                    key=lambda p: p.stat().st_mtime, 
                                    reverse=True)
                    if log_files:
                        artifacts_manager.collect_stage_env_log(run_dir_base, log_files[0])
                        print_success(f"Collected stage-env log")
                
                # Generate summary and reports
                summary_data = {
                    'run_id': run_id,
                    'test_type': 'mixed' if len(test_dirs) > 1 else 'single_suite',
                    'topology': 'default',
                    'network': 'stagenet',
                    'total_nodes': 7,
                    'exit_code': 0 if all_passed else 1,
                    'status': 'passed' if all_passed else 'failed',
                    'timestamp': datetime.now().isoformat(),
                    'total_scenarios': total_scenarios,
                    'passed_scenarios': passed_scenarios,
                    'failed_scenarios': failed_scenarios,
                    'tests_run': total_scenarios,
                    'tests_passed': passed_scenarios,
                    'tests_failed': failed_scenarios,
                    'tests_skipped': 0,
                    'scenarios': scenario_results,
                }

                all_metrics = []
                for sr in scenario_results:
                    all_metrics.extend(sr.get('metrics', []))
                if all_metrics:
                    summary_data['metrics'] = all_metrics

                # Save summary
                artifacts_manager.create_run_summary(run_dir_base, summary_data)
                
                # Generate reports
                print_info("Generating test reports...")
                report_gen = ReportGenerator(run_dir_base)
                try:
                    reports = report_gen.generate_full_report(summary_data)
                    for report_type, report_path in reports.items():
                        print_success(f"Generated {report_type}: {report_path.name}")
                except Exception as e:
                    print_warning(f"Failed to generate some reports: {e}")
                
                print_success(f"✅ All artifacts saved to: run_{run_id}/")
                
            except Exception as e:
                print_warning(f"Failed to collect some artifacts: {e}")
            
            # Stop monitoring services
            print_info("\n🔍 Stopping monitoring services...")
            try:
                # MonitoringManager is a singleton, reset it for cleanup
                MonitoringManager.reset_instance()
                print_success("Monitoring services stopped")
            except Exception as e:
                print_warning(f"Failed to stop monitoring: {e}")
            
            # Stop network if requested
            if stop_after and network_mgr:
                print_info("\n🛑 Stopping test network...")
                
                async def _stop_network():
                    await network_mgr.stop(remove_volumes=False)
                
                try:
                    asyncio.run(_stop_network())
                    print_success("Network stopped")
                except Exception as e:
                    print_warning(f"Failed to stop network cleanly: {e}")
        
        if not all_passed:
            raise typer.Exit(1)
