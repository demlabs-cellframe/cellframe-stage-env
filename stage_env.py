#!/usr/bin/env python3
"""
Stage Environment CLI - управление тестовым окружением Cellframe Node.

"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.build.builder import BuildManager
from src.certs.generator import CertGenerator
from src.config.loader import ConfigLoader
from src.network.manager import NetworkManager
from src.utils.cli import (
    check_prerequisites,
    confirm,
    format_duration,
    print_error,
    print_info,
    print_panel,
    print_success,
    print_warning,
)
from src.utils.logger import setup_logging, get_logger

# Initialize CLI app
app = typer.Typer(
    name="stage_env",
    help="🚀 Cellframe Node Stage Environment Manager",
    add_completion=False,
)

console = Console()
logger = get_logger(__name__)

# Global state
BASE_PATH = Path(__file__).parent
CONFIG_PATH: Optional[Path] = None


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging"),
    json_logs: bool = typer.Option(False, "--json", help="Output logs as JSON"),
    config: Optional[str] = typer.Option(None, "--config", help="Path to stage-env.cfg"),
):
    """Configure global options."""
    global CONFIG_PATH
    
    # Set config path from option or environment variable
    if config:
        CONFIG_PATH = Path(config).resolve()
    else:
        import os
        env_config = os.environ.get("STAGE_ENV_CONFIG")
        if env_config:
            CONFIG_PATH = Path(env_config).resolve()
    
    # Setup logging with file output
    log_file = None
    if CONFIG_PATH and CONFIG_PATH.exists():
        try:
            from configparser import ConfigParser
            cfg = ConfigParser()
            cfg.read(CONFIG_PATH)
            if cfg.has_section('logging') and cfg.has_option('logging', 'log_dir'):
                log_dir = Path(CONFIG_PATH.parent) / cfg.get('logging', 'log_dir')
                log_dir.mkdir(parents=True, exist_ok=True)
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                log_file = log_dir / f"stage-env_{timestamp}.log"
        except Exception as e:
            print(f"Warning: Failed to setup file logging: {e}", file=sys.stderr)
    
    setup_logging(verbose=verbose, json_output=json_logs, log_file=log_file)
    
    if log_file:
        logger.info("file_logging_enabled", log_file=str(log_file))


@app.command()
def build(
    clean: bool = typer.Option(False, "--clean", help="Clean build (remove build dir)"),
    release: bool = typer.Option(False, "--release", help="Release build (default: debug)"),
    jobs: int = typer.Option(0, "--jobs", "-j", help="Parallel jobs (0 = auto)"),
):
    """🔨 Build cellframe-node artifacts."""
    
    print_info("Building cellframe-node...")
    
    builder = BuildManager(BASE_PATH)
    
    build_type = "release" if release else "debug"
    result = builder.build(
        build_type=build_type,
        clean=clean,
        parallel=jobs,
    )
    
    if result.success:
        print_success(f"Build completed in {format_duration(result.duration_s)}")
        print_info(f"Artifacts: {', '.join(result.artifacts)}")
    else:
        print_error("Build failed!")
        raise typer.Exit(1)


@app.command()
def certs(
    network: str = typer.Option("stagenet", help="Network name"),
    nodes: int = typer.Option(4, help="Number of nodes"),
    validators: int = typer.Option(3, help="Number of validators"),
    force: bool = typer.Option(False, "--force", help="Regenerate even if exist"),
):
    """🔐 Generate certificates for test network."""
    
    # Load config to get correct cache_dir
    config_loader = ConfigLoader(BASE_PATH, CONFIG_PATH)
    paths_config = config_loader.get_paths_config()
    cache_dir_relative = paths_config.get('cache_dir', 'cache')
    cache_dir = (BASE_PATH / cache_dir_relative).resolve()
    certs_dir = cache_dir / "certs"
    
    cert_gen = CertGenerator(BASE_PATH, certs_dir=certs_dir)
    
    if cert_gen.certs_exist() and not force:
        if not confirm("Certificates already exist. Regenerate?", default=False):
            print_info("Keeping existing certificates")
            return
        cert_gen.clean()
    
    print_info(f"Generating certificates for {nodes} nodes + {validators} validators...")
    
    result = cert_gen.generate_all(
        network_name=network,
        node_count=nodes,
        validator_count=validators,
    )
    
    print_success(f"Generated {len(result['nodes'])} node certificates")
    print_success(f"Generated {len(result['validators'])} validator certificates")


@app.command()
def start(
    topology: str = typer.Option("default", "--topology", "-t", help="Topology to use"),
    rebuild: bool = typer.Option(False, "--rebuild", help="Rebuild images before start"),
    clean: bool = typer.Option(False, "--clean", help="Clean all data before start"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for nodes to be ready"),
):
    """▶️  Start the test network."""
    
    # Check prerequisites
    if not check_prerequisites():
        raise typer.Exit(1)
    
    # Clean if requested
    if clean:
        if not confirm("This will delete all data. Continue?", default=False):
            print_info("Cancelled")
            return
        
        print_warning("Cleaning all data...")
        # Load config to get correct cache_dir
        config_loader = ConfigLoader(BASE_PATH, CONFIG_PATH)
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', 'cache')
        cache_dir = (BASE_PATH / cache_dir_relative).resolve()
        certs_dir = cache_dir / "certs"
        
        cert_gen = CertGenerator(BASE_PATH, certs_dir=certs_dir)
        cert_gen.clean()
    
    # Start network
    network_mgr = NetworkManager(BASE_PATH, topology_name=topology, config_path=CONFIG_PATH)
    
    async def _start():
        await network_mgr.start(rebuild=rebuild, wait_ready=wait)
    
    try:
        asyncio.run(_start())
        print_success("Network started successfully!")
        
        # Show status
        _show_status(network_mgr)
        
    except Exception as e:
        print_error(f"Failed to start network: {e}")
        logger.exception("start_failed")
        raise typer.Exit(1)


@app.command()
def stop(
    volumes: bool = typer.Option(False, "--volumes", "-v", help="Remove volumes"),
):
    """⏹️  Stop the test network."""
    
    network_mgr = NetworkManager(BASE_PATH, config_path=CONFIG_PATH)
    
    async def _stop():
        await network_mgr.stop(remove_volumes=volumes)
    
    try:
        asyncio.run(_stop())
        print_success("Network stopped")
    except Exception as e:
        print_error(f"Failed to stop network: {e}")
        raise typer.Exit(1)


@app.command()
def restart(
    node: Optional[str] = typer.Argument(None, help="Node to restart (empty = all)"),
):
    """🔄 Restart network or specific node."""
    
    network_mgr = NetworkManager(BASE_PATH, config_path=CONFIG_PATH)
    
    async def _restart():
        await network_mgr.restart(node_name=node)
    
    try:
        asyncio.run(_restart())
        if node:
            print_success(f"Node {node} restarted")
        else:
            print_success("Network restarted")
    except Exception as e:
        print_error(f"Failed to restart: {e}")
        raise typer.Exit(1)


@app.command()
def status(
    topology: str = typer.Option("default", "--topology", "-t", help="Topology name"),
):
    """📊 Show network status."""
    
    network_mgr = NetworkManager(BASE_PATH, topology_name=topology, config_path=CONFIG_PATH)
    
    # Generate node configs to get info
    network_mgr.generate_node_configs()
    
    _show_status(network_mgr)


def _show_status(network_mgr: NetworkManager):
    """Helper to display network status."""
    
    async def _get_status():
        return await network_mgr.get_status()
    
    try:
        status_data = asyncio.run(_get_status())
    except Exception as e:
        print_warning(f"Could not get full status: {e}")
        return
    
    # Print summary
    print_panel(
        title="📊 Network Status",
        content=f"Network: {status_data['network_name']}\n"
                f"Topology: {status_data['topology']}\n"
                f"Total Nodes: {status_data['total_nodes']}",
        style="blue",
    )
    
    # Print node table
    table = Table(title="Nodes", show_header=True, header_style="bold magenta")
    table.add_column("Node", style="cyan")
    table.add_column("Role", style="yellow")
    table.add_column("Status", style="green")
    table.add_column("Health", style="blue")
    table.add_column("Response", style="white")
    
    nodes_list = network_mgr.list_nodes()
    health_data = status_data.get("health", {})
    
    for node in nodes_list:
        node_name = node["name"]
        health = health_data.get(node_name, {})
        
        status_emoji = "🟢" if health.get("healthy") else "🔴"
        response_time = health.get("response_time_ms", 0)
        
        table.add_row(
            node_name,
            node["role"],
            status_data["containers"].get(node_name, "unknown"),
            status_emoji,
            f"{response_time:.1f}ms" if response_time else "N/A",
        )
    
    console.print(table)


@app.command()
def logs(
    node: str = typer.Argument(..., help="Node name"),
    tail: int = typer.Option(100, "--tail", "-n", help="Number of lines"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
):
    """📜 Show logs for a node."""
    
    network_mgr = NetworkManager(BASE_PATH, config_path=CONFIG_PATH)
    
    try:
        output = network_mgr.get_node_logs(node, tail=tail, follow=follow)
        
        if follow:
            # Stream logs
            for line in output:
                console.print(line.decode("utf-8"), end="")
        else:
            console.print(output)
            
    except Exception as e:
        print_error(f"Failed to get logs: {e}")
        raise typer.Exit(1)


@app.command()
def exec(
    node: str = typer.Argument(..., help="Node name"),
    command: str = typer.Argument(..., help="Command to execute"),
):
    """⚙️  Execute command in node container."""
    
    network_mgr = NetworkManager(BASE_PATH, config_path=CONFIG_PATH)
    
    try:
        exit_code, output = network_mgr.exec_in_node(
            node,
            command.split(),
        )
        
        console.print(output)
        
        if exit_code != 0:
            raise typer.Exit(exit_code)
            
    except Exception as e:
        print_error(f"Failed to execute command: {e}")
        raise typer.Exit(1)


@app.command()
def clean(
    all: bool = typer.Option(False, "--all", help="Clean everything (build + certs + cache)"),
    build: bool = typer.Option(False, "--build", help="Clean build artifacts"),
    certs: bool = typer.Option(False, "--certs", help="Clean certificates"),
):
    """🧹 Clean build artifacts and data."""
    
    if not any([all, build, certs]):
        print_error("Specify what to clean: --all, --build, or --certs")
        raise typer.Exit(1)
    
    if all or build:
        print_info("Cleaning build artifacts...")
        builder = BuildManager(BASE_PATH)
        builder.clean()
    
    if all or certs:
        print_info("Cleaning certificates...")
        # Load config to get correct cache_dir
        config_loader = ConfigLoader(BASE_PATH, CONFIG_PATH)
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', 'cache')
        cache_dir = (BASE_PATH / cache_dir_relative).resolve()
        certs_dir = cache_dir / "certs"
        
        cert_gen = CertGenerator(BASE_PATH, certs_dir=certs_dir)
        cert_gen.clean()
    
    print_success("Cleanup completed")


@app.command()
def run_tests(
    test_dirs: list[str] = typer.Argument(..., help="Test scenario directories to run"),
    parallel: bool = typer.Option(False, "--parallel", "-p", help="Run tests in parallel"),
    filter: Optional[str] = typer.Option(None, "--filter", "-k", help="Filter tests by pattern"),
):
    """🧪 Run test scenarios from specified directories."""
    
    import subprocess
    from pathlib import Path
    
    print_info(f"Running tests from {len(test_dirs)} director{'y' if len(test_dirs) == 1 else 'ies'}:")
    for test_dir in test_dirs:
        print_info(f"  • {test_dir}")
    
    all_passed = True
    
    for test_dir in test_dirs:
        test_path = Path(test_dir).resolve()
        
        if not test_path.exists():
            print_warning(f"Directory not found: {test_path}")
            continue
        
        print_info(f"Running tests from {test_path.name}...")
        
        # Run pytest for the directory
        cmd = ["pytest", "-v", str(test_path)]
        
        if filter:
            cmd.extend(["-k", filter])
        
        if parallel:
            cmd.extend(["-n", "auto"])
        
        try:
            result = subprocess.run(cmd)
            if result.returncode != 0:
                all_passed = False
                print_error(f"Tests from {test_path.name} failed")
            else:
                print_success(f"Tests from {test_path.name} passed")
        except FileNotFoundError:
            print_error("pytest not found. Install with: pip install pytest pytest-asyncio")
            raise typer.Exit(1)
    
    if not all_passed:
        raise typer.Exit(1)


@app.command()
def snapshots_list():
    """📦 List all available topology snapshots."""
    from src.snapshots import TopologySnapshotManager
    
    cache_dir = BASE_PATH / "cache"
    snapshot_mgr = TopologySnapshotManager(cache_dir)
    
    snapshots = snapshot_mgr.list_snapshots()
    
    if not snapshots:
        print_info("No snapshots found")
        return
    
    table = Table(title="📦 Topology Snapshots")
    table.add_column("Hash", style="cyan")
    table.add_column("Nodes", justify="right")
    table.add_column("Consensus", style="yellow")
    table.add_column("Size", justify="right", style="green")
    table.add_column("Version")
    table.add_column("Age")
    table.add_column("Status", style="magenta")
    
    for snapshot in snapshots:
        status = "✅ Valid" if snapshot['valid'] else "❌ Invalid"
        
        table.add_row(
            snapshot['topology_hash_short'],
            str(snapshot['node_count']),
            snapshot['consensus_type'],
            snapshot['size'],
            snapshot['version'],
            snapshot['created'].split('T')[0] if 'T' in snapshot['created'] else snapshot['created'],
            status,
        )
    
    console.print(table)
    
    # Show total size
    total_size = snapshot_mgr.get_total_size()
    from src.snapshots.utils import format_size
    print_info(f"Total snapshot size: {format_size(total_size)}")


@app.command()
def snapshots_delete(
    topology_hash: str = typer.Argument(..., help="Topology hash to delete (or 'all' for all snapshots)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """🗑️  Delete topology snapshot(s)."""
    from src.snapshots import TopologySnapshotManager
    
    cache_dir = BASE_PATH / "cache"
    snapshot_mgr = TopologySnapshotManager(cache_dir)
    
    if topology_hash.lower() == 'all':
        snapshots = snapshot_mgr.list_snapshots()
        if not snapshots:
            print_info("No snapshots to delete")
            return
        
        if not yes and not confirm(f"Delete {len(snapshots)} snapshot(s)?"):
            print_info("Cancelled")
            return
        
        deleted_count = 0
        for snapshot in snapshots:
            if snapshot_mgr.delete(snapshot['topology_hash']):
                deleted_count += 1
        
        print_success(f"Deleted {deleted_count} snapshot(s)")
    else:
        # Find snapshot by prefix
        snapshots = snapshot_mgr.list_snapshots()
        matching = [s for s in snapshots if s['topology_hash'].startswith(topology_hash)]
        
        if not matching:
            print_error(f"Snapshot not found: {topology_hash}")
            raise typer.Exit(1)
        
        if len(matching) > 1:
            print_error(f"Ambiguous hash prefix. Found {len(matching)} matches:")
            for s in matching:
                print_info(f"  {s['topology_hash_short']}")
            raise typer.Exit(1)
        
        snapshot = matching[0]
        full_hash = snapshot['topology_hash']
        
        if not yes and not confirm(f"Delete snapshot {snapshot['topology_hash_short']}?"):
            print_info("Cancelled")
            return
        
        if snapshot_mgr.delete(full_hash):
            print_success(f"Deleted snapshot: {snapshot['topology_hash_short']}")
        else:
            print_error("Failed to delete snapshot")
            raise typer.Exit(1)


@app.command()
def snapshots_info(
    topology_hash: str = typer.Argument(..., help="Topology hash (or prefix)"),
):
    """ℹ️  Show detailed snapshot information."""
    from src.snapshots import TopologySnapshotManager
    import json
    
    cache_dir = BASE_PATH / "cache"
    snapshot_mgr = TopologySnapshotManager(cache_dir)
    
    # Find snapshot by prefix
    snapshots = snapshot_mgr.list_snapshots()
    matching = [s for s in snapshots if s['topology_hash'].startswith(topology_hash)]
    
    if not matching:
        print_error(f"Snapshot not found: {topology_hash}")
        raise typer.Exit(1)
    
    if len(matching) > 1:
        print_error(f"Ambiguous hash prefix. Found {len(matching)} matches:")
        for s in matching:
            print_info(f"  {s['topology_hash_short']}")
        raise typer.Exit(1)
    
    snapshot = matching[0]
    info = snapshot_mgr.get_info(snapshot['topology_hash'])
    
    if not info:
        print_error("Failed to get snapshot info")
        raise typer.Exit(1)
    
    print_panel(f"📦 Snapshot: {info['topology_hash'][:16]}...", "Snapshot Information")
    print_info(f"Path: {info['path']}")
    print_info(f"Size: {info['size']}")
    print_info(f"Nodes: {info['node_count']}")
    print_info(f"Consensus: {info['consensus_type']}")
    print_info(f"Version: {info['version']}")
    print_info(f"Created: {info['created']}")
    print_info(f"Compression: {info['compression_ratio']}x")
    print_info(f"Valid: {'✅ Yes' if info['valid'] else '❌ No'}")
    
    # Show metadata
    print_info("\nMetadata:")
    console.print_json(json.dumps(info['metadata'], indent=2))


@app.command()
def snapshots_clean(
    max_age_days: int = typer.Option(30, "--max-age", help="Maximum age in days"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """🧹 Clean expired snapshots."""
    from src.snapshots import TopologySnapshotManager
    
    cache_dir = BASE_PATH / "cache"
    snapshot_mgr = TopologySnapshotManager(cache_dir)
    
    if not yes and not confirm(f"Delete snapshots older than {max_age_days} days?"):
        print_info("Cancelled")
        return
    
    print_info(f"Cleaning snapshots older than {max_age_days} days...")
    deleted_count = snapshot_mgr.clean_expired(max_age_days)
    
    if deleted_count > 0:
        print_success(f"Deleted {deleted_count} expired snapshot(s)")
    else:
        print_info("No expired snapshots found")


@app.command("collect-artifacts")
def collect_artifacts(
    ctx: typer.Context,
    test_type: str = typer.Argument(..., help="Test type: e2e, functional, or all"),
    exit_code: int = typer.Option(0, help="Test exit code"),
):
    """📦 Collect artifacts and generate reports after test run."""
    import docker
    from datetime import datetime
    from src.utils.artifacts import ArtifactsManager
    from src.utils.report_generator import ReportGenerator
    
    print_info(f"Collecting artifacts for {test_type} tests (exit code: {exit_code})")
    
    # Load configuration
    config_loader = ConfigLoader(BASE_PATH, CONFIG_PATH)
    artifacts_config = config_loader.get_artifacts_config()
    
    # Initialize artifacts manager
    artifacts_manager = ArtifactsManager(BASE_PATH, artifacts_config)
    
    # Create run directory
    run_id = f"{test_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = artifacts_manager.create_run_directory(run_id)
    
    print_info(f"Created run directory: {run_dir.name}")
    
    # Collect stage-env log (use log_dir from config)
    logging_config = config_loader.get_logging_config()
    log_dir_relative = logging_config.get('log_dir', 'logs')
    log_dir = (CONFIG_PATH.parent / log_dir_relative).resolve() if CONFIG_PATH else (BASE_PATH.parent / "logs")
    if log_dir.exists():
        log_files = sorted(log_dir.glob("stage-env_*.log"), 
                          key=lambda p: p.stat().st_mtime, 
                          reverse=True)
        if log_files:
            artifacts_manager.collect_stage_env_log(run_dir, log_files[0])
            print_success(f"Collected stage-env log: {log_files[0].name}")
    
    # Collect node logs from Docker containers
    try:
        client = docker.from_env()
        project_name = "cellframe-stage"
        
        containers = client.containers.list(
            all=True,
            filters={"label": f"com.docker.compose.project={project_name}"}
        )
        
        node_logs_dir = run_dir / "node-logs"
        core_dumps_dir = run_dir / "core-dumps"
        
        collected_logs = 0
        collected_dumps = 0
        
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
                    
                    # Check for core dumps
                    crash_dir = f"/crash-artifacts/{node_id}"
                    result = container.exec_run(f"ls {crash_dir}", demux=False)
                    if result.exit_code == 0 and result.output:
                        files = result.output.decode('utf-8').strip().split('\n')
                        for file in files:
                            if file and file != '.':
                                dump_result = container.exec_run(
                                    f"cat {crash_dir}/{file}",
                                    demux=False
                                )
                                if dump_result.exit_code == 0:
                                    dump_file = core_dumps_dir / f"{node_id}_{file}"
                                    dump_file.write_bytes(dump_result.output)
                                    collected_dumps += 1
            except Exception as e:
                logger.warning("failed_to_collect_container_artifacts",
                             container=container.name,
                             error=str(e))
        
        print_success(f"Collected {collected_logs} node logs")
        if collected_dumps > 0:
            print_warning(f"Collected {collected_dumps} core dumps ⚠️")
        
    except Exception as e:
        print_error(f"Failed to collect Docker artifacts: {e}")
    
    # Collect health logs
    artifacts_manager.collect_health_logs(run_dir)
    
    # Build summary data
    summary_data = {
        'run_id': run_id,
        'test_type': test_type,
        'exit_code': exit_code,
        'status': 'passed' if exit_code == 0 else 'failed',
        'timestamp': datetime.now().isoformat(),
        'topology': 'default',
        'network': 'stagenet',
        'total_nodes': 7,
        'artifacts': {
            'node_logs': [str(p.name) for p in (run_dir / "node-logs").glob("*.log")],
            'stage_env_logs': [str(p.name) for p in (run_dir / "stage-env-logs").glob("*.log")],
            'core_dumps': [str(p.name) for p in (run_dir / "core-dumps").glob("*")],
            'stack_traces': [str(p.name) for p in (run_dir / "stack-traces").glob("*")],
        }
    }
    
    # Create summary file
    artifacts_manager.create_run_summary(run_dir, summary_data)
    print_success("Created summary.json")
    
    # Generate reports
    print_info("Generating reports...")
    report_generator = ReportGenerator(run_dir)
    reports = report_generator.generate_full_report(summary_data)
    
    for report_type, report_path in reports.items():
        print_success(f"Generated {report_type} report: {report_path.name}")
    
    # Cleanup old artifacts
    print_info("Cleaning up old artifacts...")
    artifacts_manager.cleanup_old_artifacts()
    
    print_panel(
        f"✅ Artifacts collected: [cyan]{run_dir}[/cyan]\n\n"
        f"📊 Reports:\n"
        + "\n".join([f"  • {t}: {p.relative_to(run_dir)}" for t, p in reports.items()]),
        title="Artifacts Collection Complete"
    )


if __name__ == "__main__":
    app()

