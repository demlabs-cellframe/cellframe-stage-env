"""
CLI commands for network management.
"""
import asyncio
import typer
from pathlib import Path
from typing import Callable, Optional

from .common import print_info, print_success, print_error, print_warning
from src.utils.i18n import _
from src.utils.project import make_container_name


def register_commands(app: typer.Typer, base_path: Path, get_config_path: Callable[[], Optional[Path]]):
    """Register network management commands."""
    
    @app.command()
    def build(
        clean: bool = typer.Option(False, "--clean", help="Clean build"),
        release: bool = typer.Option(False, "--release", help="Release build"),
        jobs: int = typer.Option(0, "--jobs", "-j", help="Parallel jobs"),
    ):
        """🔨 Build cellframe-node artifacts."""
        from ..build.manager import BuildManager
        
        print_info(_("Building cellframe-node..."))
        builder = BuildManager(base_path)
        build_type = "release" if release else "debug"
        result = builder.build(build_type=build_type, clean=clean, parallel=jobs)
        
        if result.success:
            # Format duration inline
            duration = result.duration_s
            if duration < 1:
                duration_str = f"{duration * 1000:.0f}ms"
            elif duration < 60:
                duration_str = f"{duration:.1f}s"
            else:
                minutes = int(duration // 60)
                secs = int(duration % 60)
                duration_str = f"{minutes}m {secs}s"
            
            print_success(_("Build completed in {}").format(duration_str))
            print_info(_("Artifacts: {}").format(', '.join(result.artifacts)))
        else:
            print_error(_("Build failed!"))
            raise typer.Exit(1)
    
    @app.command()
    def start(
        topology: str = typer.Option("default", "--topology", "-t", help="Topology to use"),
        rebuild: bool = typer.Option(False, "--rebuild", help="Rebuild images"),
        clean: bool = typer.Option(False, "--clean", help="Clean all data"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompts"),
        wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for nodes"),
        keep_running: bool = typer.Option(False, "--keep-running", help="Keep containers running on failure (for debugging)"),
    ):
        """▶️  Start the test network."""
        from ..network.manager import NetworkManager
        from ..config.manager import get_config_loader
        from ..certs.generator import CertGenerator
        
        # Check prerequisites inline
        import shutil
        import subprocess
        
        # Check for docker
        if not shutil.which("docker"):
            print_error(_("Missing required tool: docker"))
            print_info(_("Please install Docker"))
            raise typer.Exit(1)
        
        # Check for docker compose (V2) or docker-compose (V1)
        has_compose = False
        if shutil.which("docker"):
            # Try docker compose (V2)
            result = subprocess.run(["docker", "compose", "version"], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                has_compose = True
            # Fallback to docker-compose (V1)
            elif shutil.which("docker-compose"):
                has_compose = True
        
        if not has_compose:
            print_error(_("Missing Docker Compose"))
            print_info(_("Please install Docker Compose (either V1 or V2)"))
            raise typer.Exit(1)
        
        if clean:
            if not yes:
                from rich.prompt import Confirm
                if not Confirm.ask(_("This will delete all data. Continue?"), default=False):
                    print_info(_("Cancelled"))
                    return

            print_warning(_("Cleaning all data..."))
            config_loader = get_config_loader()
            paths_config = config_loader.get_paths_config()
            cache_dir_relative = paths_config.get("cache_dir", "cache")
            cache_dir = (base_path / cache_dir_relative).resolve()
            certs_dir = cache_dir / "certs"

            cert_gen = CertGenerator(base_path, certs_dir=certs_dir)
            cert_gen.clean()

            # Clean snapshots so genesis can run from scratch
            snapshots_config = config_loader.get_suite_isolation_config()
            snapshots_dir = (base_path / snapshots_config.get("snapshots_dir", "../../cache/snapshots")).resolve()
            if snapshots_dir.exists():
                from ..snapshots.manager import SnapshotManager, SnapshotMode
                mode_str = snapshots_config.get("mode", "filesystem").lower()
                mode_map = {
                    "disabled": SnapshotMode.DISABLED,
                    "recreate": SnapshotMode.RECREATE,
                    "filesystem": SnapshotMode.FILESYSTEM,
                    "squashfs": SnapshotMode.SQUASHFS,
                }
                snapshot_mode = mode_map.get(mode_str, SnapshotMode.FILESYSTEM)
                snapshot_mgr = SnapshotManager(base_path, snapshot_mode, snapshots_config)
                async def _clean_snapshots():
                    for name in await snapshot_mgr.list_snapshots():
                        await snapshot_mgr.delete_snapshot(name)
                asyncio.run(_clean_snapshots())
                print_info(_("Snapshots cleaned"))

        # NetworkManager will use global config loader
        network_mgr = NetworkManager(base_path, topology_name=topology, config_path=get_config_path())
        network_mgr.keep_running = keep_running
        
        async def _start():
            await network_mgr.start(rebuild=rebuild, wait_ready=wait)
        
        try:
            asyncio.run(_start())
            print_success(_("Network started successfully!"))
            _show_status(network_mgr)
            
            # Create pristine network marker for test optimization
            # First suite will use this network directly without restore
            config_loader = get_config_loader()
            paths_config = config_loader.get_paths_config()
            artifacts_dir = paths_config.get('artifacts_dir', '../../cache/artifacts')
            artifacts_path = (base_path / artifacts_dir).resolve()
            artifacts_path.mkdir(parents=True, exist_ok=True)
            pristine_marker = artifacts_path / ".pristine_network"
            pristine_marker.touch()
            print_info(_("🎯 Pristine network marker created - first suite will use it directly"))
        except Exception as e:
            print_error(_("Failed to start network: {}").format(e))
            raise typer.Exit(1)
    
    @app.command()
    def stop(
        volumes: bool = typer.Option(False, "--volumes", "-v", help="Remove volumes"),
    ):
        """⏹️  Stop the test network."""
        from ..network.manager import NetworkManager
        
        config_path = get_config_path()
        network_mgr = NetworkManager(base_path, config_path=config_path)
        
        async def _stop():
            await network_mgr.stop(remove_volumes=volumes)
        
        try:
            asyncio.run(_stop())
            print_success(_("Network stopped"))
        except Exception as e:
            print_error(_("Failed to stop network: {}").format(e))
            raise typer.Exit(1)
    
    @app.command()
    def kill(
        timeout: int = typer.Option(10, "--timeout", "-t", help="Timeout in seconds before force kill"),
    ):
        """🛑 Kill the test network gracefully (SIGTERM)."""
        from ..network.manager import NetworkManager
        from src.utils.pid_manager import PIDManager
        
        config_path = get_config_path()
        network_mgr = NetworkManager(base_path, config_path=config_path)
        
        try:
            network_mgr.compose.kill(timeout=timeout)
            print_success(_("Network killed (timeout: {}s)").format(timeout))
            
            # Remove PID file after successful kill
            pid_mgr = PIDManager(base_path)
            pid_mgr.remove()
        except Exception as e:
            print_error(_("Failed to kill network: {}").format(e))
            raise typer.Exit(1)
    
    @app.command()
    def terminate():
        """💀 Force terminate the test network (SIGKILL)."""
        from ..network.manager import NetworkManager
        from src.utils.pid_manager import PIDManager
        
        config_path = get_config_path()
        network_mgr = NetworkManager(base_path, config_path=config_path)
        
        try:
            network_mgr.compose.terminate()
            print_success(_("Network terminated"))
            
            # Remove PID file after successful terminate
            pid_mgr = PIDManager(base_path)
            pid_mgr.remove()
        except Exception as e:
            print_error(_("Failed to terminate network: {}").format(e))
            raise typer.Exit(1)
    
    @app.command()
    def restart(
        wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for nodes"),
    ):
        """🔄 Restart the test network."""
        from ..network.manager import NetworkManager
        
        config_path = get_config_path()
        network_mgr = NetworkManager(base_path, config_path=config_path)
        
        async def _restart():
            await network_mgr.restart(wait_ready=wait)
        
        try:
            asyncio.run(_restart())
            print_success(_("Network restarted"))
            _show_status(network_mgr)
        except Exception as e:
            print_error(_("Failed to restart network: {}").format(e))
            raise typer.Exit(1)
    
    @app.command()
    def status():
        """📊 Show network status."""
        from ..network.manager import NetworkManager
        
        config_path = get_config_path()
        network_mgr = NetworkManager(base_path, config_path=config_path)
        
        async def _get_status():
            return await network_mgr.get_status()
        
        try:
            status_data = asyncio.run(_get_status())
        except Exception as e:
            print_warning(_("Could not get full status: {}").format(e))
            return
        
        _print_status_table(status_data)
    
    @app.command()
    def logs(
        node: str = typer.Argument(..., help="Node ID (e.g., node1)"),
        follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
        tail: int = typer.Option(100, "--tail", "-n", help="Number of lines"),
    ):
        """📜 Show logs from a specific node."""
        import subprocess
        
        container_name = make_container_name(node)
        cmd = ["docker", "logs"]
        if follow:
            cmd.append("-f")
        cmd.extend(["--tail", str(tail), container_name])
        
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print_error(_("Failed to get logs: {}").format(e))
            raise typer.Exit(1)
    
    @app.command()
    def exec(
        node: str = typer.Argument(..., help="Node ID (e.g., node1)"),
        command: str = typer.Argument(..., help="Command to execute"),
    ):
        """⚡ Execute command on a node."""
        import subprocess
        
        container_name = make_container_name(node)
        cmd = ["docker", "exec", "-it", container_name, "sh", "-c", command]
        
        try:
            subprocess.run(cmd)
        except Exception as e:
            print_error(_("Failed to execute command: {}").format(e))
            raise typer.Exit(1)
    
    @app.command()
    def rebuild():
        """🔧 Rebuild all Docker images and restart network."""
        from ..network.manager import NetworkManager
        from ..config.manager import get_config_loader
        from ..certs.generator import CertGenerator
        
        print_info(_("Starting full environment rebuild..."))
        
        # Stop network
        print_info(_("\n🛑 Stopping network..."))
        config_path = get_config_path()
        network_mgr = NetworkManager(base_path, config_path=config_path)
        
        async def _stop():
            await network_mgr.stop(remove_volumes=False)
        
        try:
            asyncio.run(_stop())
            print_success(_("Network stopped"))
        except Exception as e:
            print_warning(_("Network was not running: {}").format(e))
        
        # Rebuild cert-generator
        print_info(_("\n🔨 Rebuilding cert-generator image..."))
        import subprocess
        cert_gen_dir = base_path / "cellframe-sdk" / "dap-sdk" / "crypto" / "tools" / "cert-generator"
        if cert_gen_dir.exists():
            result = subprocess.run(
                ["docker", "build", "-t", "demlabs-cellframe-cert-generator", "."],
                cwd=cert_gen_dir,
                capture_output=True
            )
            if result.returncode == 0:
                print_success(_("Cert-generator rebuilt"))
            else:
                print_warning(_("Failed to rebuild cert-generator"))
        
        # Clean and regenerate certs
        print_info(_("\n🔐 Regenerating certificates..."))
        config_loader = get_config_loader()
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', 'cache')
        cache_dir = (base_path / cache_dir_relative).resolve()
        certs_dir = cache_dir / "certs"
        
        cert_gen = CertGenerator(base_path, certs_dir=certs_dir)
        cert_gen.clean()
        
        try:
            cert_gen.generate_all()
            print_success(_("Certificates regenerated"))
        except Exception as e:
            print_error(_("Failed to regenerate certificates: {}").format(e))
            raise typer.Exit(1)
        
        # Rebuild cellframe images
        print_info(_("\n🔨 Rebuilding cellframe-node images..."))
        
        async def _start():
            await network_mgr.start(rebuild=True, wait_ready=True)
        
        try:
            asyncio.run(_start())
            print_success(_("Network rebuilt and started"))
        except Exception as e:
            print_error(_("Failed to rebuild network: {}").format(e))
            raise typer.Exit(1)
        
        # Show status
        print_info(_("\n📊 Network Status:"))
        _show_status(network_mgr)
        
        print_success(_("\n✅ Full rebuild completed!"))
    
    @app.command()
    def pkgs_update():
        """📦 Update packages in containers (copy binary + apt update/upgrade). Starts containers if needed."""
        from ..network.manager import NetworkManager
        from ..build.builder import BuildManager
        from ..config.manager import get_config_loader
        import tarfile
        import io
        
        config_path = get_config_path()
        config_loader = get_config_loader()
        
        paths_config = config_loader.get_paths_config()
        project_root = (base_path / paths_config.get('project_root', '../..')).resolve()
        build_dir = project_root / "build"
        
        binaries = ["cellframe-node", "cellframe-node-cli", "cellframe-node-tool"]
        found_binaries = []
        for name in binaries:
            p = build_dir / name
            if p.exists():
                found_binaries.append(p)
                print_info(_("Found binary: {}").format(p))
            else:
                print_warning(_("Binary not found (skipping): {}").format(p))
        
        if not found_binaries:
            print_error(_("No binaries found in {}").format(build_dir))
            print_info(_("Please build cellframe-node first: ./stage-env build"))
            raise typer.Exit(1)
        
        # Initialize network manager to get containers
        network_mgr = NetworkManager(base_path, config_path=config_path)
        
        # Get ALL containers (including stopped ones)
        all_containers = network_mgr.compose.ps()
        
        if not all_containers:
            print_warning(_("No containers found for this project"))
            print_info(_("Starting containers (without genesis)..."))
            # Start containers directly using compose.up() (without genesis scenario)
            try:
                network_mgr.compose.up(detach=True, wait=False)
                # Wait a bit for containers to start
                import time
                time.sleep(5)
                all_containers = network_mgr.compose.ps()
                if not all_containers:
                    print_error(_("Failed to start containers"))
                    raise typer.Exit(1)
                print_success(_("Started {} container(s)").format(len(all_containers)))
            except Exception as e:
                print_error(_("Failed to start containers: {}").format(e))
                raise typer.Exit(1)
        
        # Separate running and stopped containers
        running_containers = [c for c in all_containers if c.status == "running"]
        stopped_containers = [c for c in all_containers if c.status != "running"]
        
        print_info(_("Found {} container(s): {} running, {} stopped").format(len(all_containers), len(running_containers), len(stopped_containers)))
        
        # Start stopped containers if needed
        if stopped_containers:
            print_info(_("Starting {} stopped container(s)...").format(len(stopped_containers)))
            for container in stopped_containers:
                try:
                    print_info(_("  → Starting {}").format(container.name))
                    container.start()
                    # Wait a bit for container to be ready
                    import time
                    time.sleep(2)
                    print_success(_("  ✓ {} started").format(container.name))
                except Exception as e:
                    print_error(_("  ✗ Failed to start {}: {}").format(container.name, e))
            
            # Refresh container list after starting
            all_containers = network_mgr.compose.ps()
            running_containers = [c for c in all_containers if c.status == "running"]
        
        if not running_containers:
            print_error(_("No running containers available for update"))
            raise typer.Exit(1)
        
        # Create tar archive with all found binaries
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode='w') as tar:
            for bp in found_binaries:
                tar.add(str(bp), arcname=bp.name)
        tar_data = tar_stream.getvalue()
        
        bin_names = [bp.name for bp in found_binaries]
        print_info(_("Copying {} binaries ({}) to {} container(s)...").format(len(bin_names), ', '.join(bin_names), len(running_containers)))
        for container in running_containers:
            try:
                print_info(_("  → {}").format(container.name))
                
                container.put_archive("/tmp", tar_data)
                
                mv_cmds = " && ".join(
                    f"mv /tmp/{name} /opt/cellframe-node/bin/{name} && chmod +x /opt/cellframe-node/bin/{name}"
                    for name in bin_names
                )
                container.exec_run(["sh", "-c", mv_cmds], user="root")
                
                print_success(_("  ✓ {} binaries updated in {}").format(len(bin_names), container.name))
            except Exception as e:
                print_error(_("  ✗ Failed to update binaries in {}: {}").format(container.name, e))
        
        # Update packages in containers
        print_info(_("Updating packages in {} container(s)...").format(len(running_containers)))
        for container in running_containers:
            try:
                print_info(_("  → {}").format(container.name))
                
                # apt update
                result = container.exec_run(
                    ["apt-get", "update"],
                    user="root"
                )
                if result.exit_code != 0:
                    print_warning(_("  ⚠ apt-get update failed in {}").format(container.name))
                
                # apt upgrade (non-interactive)
                result = container.exec_run(
                    ["sh", "-c", "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y"],
                    user="root"
                )
                if result.exit_code != 0:
                    print_warning(_("  ⚠ apt-get upgrade failed in {}").format(container.name))
                else:
                    print_success(_("  ✓ Packages updated in {}").format(container.name))
            except Exception as e:
                print_error(_("  ✗ Failed to update packages in {}: {}").format(container.name, e))
        
        print_success(_("Package update completed"))


def _show_status(network_mgr):
    """Show network status (helper function)."""
    async def _get_status():
        return await network_mgr.get_status()
    
    try:
        status_data = asyncio.run(_get_status())
        _print_status_table(status_data)
    except Exception as e:
        print_warning(_("Could not get status: {}").format(e))


def _print_status_table(status_data):
    """Print status table (helper function)."""
    from rich.table import Table
    from rich.console import Console
    from .common import print_panel
    
    console = Console()
    
    # Check if status_data has required fields
    if not isinstance(status_data, dict):
        print_warning(_("Invalid status data: expected dict, got {}").format(type(status_data)))
        return
    
    # Print basic info
    network_name = status_data.get('network_name', 'N/A')
    topology = status_data.get('topology', 'N/A')
    total_nodes = status_data.get('total_nodes', 0)
    content = "\n".join([
        _("Network: {}").format(network_name),
        _("Topology: {}").format(topology),
        _("Total Nodes: {}").format(total_nodes),
    ])
    print_panel(
        title=_("📊 Network Status"),
        content=content,
        style="cyan"
    )
    
    # Check if nodes data is available
    nodes = status_data.get('nodes', [])
    if not nodes:
        print_warning(_("No node status information available"))
        return
    
    table = Table(title=_("🖥️  Nodes"))
    table.add_column(_("Node"), style="cyan", no_wrap=True)
    table.add_column(_("Role"), style="yellow")
    table.add_column(_("Container"), style="magenta")
    table.add_column(_("Health"), style="green")
    table.add_column(_("Ports"), style="blue")
    
    for node in nodes:
        # Determine status emoji and text
        healthy = node.get('healthy', False)
        health_status = node.get('health_status', 'unknown')
        container_status = node.get('container_status', 'unknown')
        
        if healthy and health_status == "NET_STATE_ONLINE":
            status_emoji = "🟢"
            status_text = _("Online")
        elif container_status == "running":
            status_emoji = "🟡"
            status_text = health_status
        else:
            status_emoji = "🔴"
            status_text = container_status
        
        # Format ports
        rpc_port = node.get('rpc_port', 'N/A')
        p2p_port = node.get('p2p_port', 'N/A')
        ports_text = f"RPC:{rpc_port}, P2P:{p2p_port}"
        
        table.add_row(
            node.get('name', 'N/A'),
            node.get('role', 'N/A'),
            container_status,
            f"{status_emoji} {status_text}",
            ports_text
        )
    
    console.print(table)

