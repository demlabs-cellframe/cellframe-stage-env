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
    
    setup_logging(verbose=verbose, json_output=json_logs)


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
    
    cert_gen = CertGenerator(BASE_PATH)
    
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
        cert_gen = CertGenerator(BASE_PATH)
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
        cert_gen = CertGenerator(BASE_PATH)
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


if __name__ == "__main__":
    app()

