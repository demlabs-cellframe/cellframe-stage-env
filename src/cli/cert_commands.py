"""
CLI commands for certificate management.
"""
import sys
import typer
from pathlib import Path
from typing import Callable, Optional

from .common import print_info, print_success, print_error, print_warning, confirm


def register_commands(app: typer.Typer, base_path: Path, get_config_path: Callable[[], Optional[Path]]):
    """Register certificate management commands."""
    
    @app.command()
    def certs(
        network: str = typer.Option("stagenet", help="Network name"),
        nodes: int = typer.Option(4, help="Number of nodes"),
        validators: int = typer.Option(3, help="Number of validators"),
        force: bool = typer.Option(False, "--force", help="Regenerate even if exist"),
    ):
        """🔐 Generate certificates for test network."""
        from ..certs.generator import CertGenerator
        from ..config.manager import get_config_loader
        
        # Load config to get correct cache_dir
        config_loader = get_config_loader()
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', 'cache')
        cache_dir = (base_path / cache_dir_relative).resolve()
        certs_dir = cache_dir / "certs"
        
        cert_gen = CertGenerator(base_path, certs_dir=certs_dir)
        
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
        print_info(f"Certificates saved to: {certs_dir}")
    
    @app.command()
    def clean(
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
        all: bool = typer.Option(False, "--all", "-a", help="Clean everything (certificates, configs, data, snapshots)"),
    ):
        """🧹 Clean up generated certificates and cache."""
        from ..certs.generator import CertGenerator
        from ..config.generator import ConfigGenerator
        from ..config.manager import get_config_loader
        from ..snapshots.manager import SnapshotManager, SnapshotMode
        from ..docker.compose import DockerComposeManager
        
        # Skip confirmation if --yes or --all is used
        if not yes and not all:
            if not confirm("This will delete all generated certificates and cache. Continue?", default=False):
                print_info("Cancelled")
                return
        
        config_loader = get_config_loader()
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', 'cache')
        cache_dir = (base_path / cache_dir_relative).resolve()
        certs_dir = cache_dir / "certs"
        configs_dir = cache_dir / "configs"
        data_dir = cache_dir / "data"
        
        # Clean certificates
        cert_gen = CertGenerator(base_path, certs_dir=certs_dir)
        cert_gen.clean()
        print_success("Cleaned certificates")
        
        if all:
            # Initialize Docker client for cleanup (no need for compose project)
            compose_mgr = None
            try:
                import docker
                docker_client = docker.from_env()
                # Create minimal compose manager just for cleanup
                compose_mgr = DockerComposeManager(base_path, project_name="stage_env_cleanup")
                print_info("Using Docker for cleanup")
            except Exception as e:
                print_warning(f"Could not initialize Docker cleanup, falling back to sudo: {e}")
                compose_mgr = None
            
            # Clean configs using Docker if available, otherwise sudo
            if configs_dir.exists():
                print_info("Cleaning configs...")
                try:
                    if compose_mgr:
                        # Use Docker for cleanup
                        print_info("Removing configs via Docker container...")
                        container = compose_mgr.client.containers.run(
                            image="alpine:latest",
                            command=["sh", "-c", "rm -rf /cleanup/configs && echo 'Configs cleaned'"],
                            volumes={
                                str(cache_dir.absolute()): {
                                    'bind': '/cleanup',
                                    'mode': 'rw'
                                }
                            },
                            remove=True,
                            detach=False,
                        )
                    else:
                        # Fallback to sudo
                        print_warning("Falling back to sudo for configs cleanup")
                        import subprocess
                        subprocess.run(["sudo", "rm", "-rf", str(configs_dir)], check=True)
                    configs_dir.mkdir(parents=True, exist_ok=True)
                    print_success("Cleaned configs")
                except Exception as e:
                    print_error(f"Failed to clean configs: {e}")
                    sys.exit(1)
            
            # Clean data using Docker
            if data_dir.exists():
                print_info("Cleaning cache/data...")
                try:
                    if compose_mgr:
                        print_info("Removing cache/data via Docker container...")
                        compose_mgr.clean_cache_data(cache_dir)
                    else:
                        # Fallback to sudo
                        print_warning("Falling back to sudo for data cleanup")
                        import subprocess
                        subprocess.run(["sudo", "rm", "-rf", str(data_dir)], check=True)
                        data_dir.mkdir(parents=True, exist_ok=True)
                    print_success("Cleaned cache/data")
                except Exception as e:
                    print_error(f"Failed to clean data: {e}")
                    sys.exit(1)
            
            # Clean snapshots
            print_info("Removing snapshots...")
            try:
                snapshots_config = config_loader.get_suite_isolation_config()
                snapshots_dir_relative = snapshots_config.get('snapshots_dir', '../../cache/snapshots')
                snapshots_dir = (base_path / snapshots_dir_relative).resolve()
                
                if snapshots_dir.exists():
                    # Use snapshot manager to clean
                    import asyncio
                    
                    # Check if event loop is already running
                    try:
                        loop = asyncio.get_running_loop()
                        print_error("Cannot run async code: event loop already running")
                        sys.exit(1)
                    except RuntimeError:
                        pass
                    
                    snapshot_manager = SnapshotManager(base_path, config=snapshots_config)
                    
                    # Delete all snapshots
                    async def delete_all_snapshots():
                        try:
                            snapshots = await snapshot_manager.list_snapshots()
                            for snapshot_name in snapshots:
                                await snapshot_manager.delete_snapshot(snapshot_name)
                        except Exception as e:
                            print_error(f"Error deleting snapshots: {e}")
                            raise
                    
                    asyncio.run(delete_all_snapshots())
                    print_success("Snapshots cleaned")
                else:
                    print_info("No snapshots directory found")
            except Exception as e:
                print_error(f"Failed to clean snapshots: {e}")
                sys.exit(1)
            
            # Clean Docker networks (including conflicting ones)
            print_info("Cleaning Docker networks...")
            try:
                import docker
                docker_client = docker.from_env()
                
                # Find and remove all test-related networks
                all_networks = docker_client.networks.list()
                test_networks = [
                    net for net in all_networks
                    if any(pattern in net.name for pattern in [
                        'cellframe-stage',
                        'stage-env',
                        'stagenet'
                    ])
                ]
                
                if test_networks:
                    print_info(f"Found {len(test_networks)} test network(s) to remove...")
                    for network in test_networks:
                        try:
                            # Check if network has active endpoints
                            network.reload()
                            if network.containers:
                                print_info(f"Stopping containers on network {network.name}...")
                                for container in network.containers:
                                    try:
                                        container.stop(timeout=5)
                                        container.remove()
                                    except Exception as e:
                                        print_warning(f"Could not remove container {container.name}: {e}")
                            
                            network.remove()
                            print_info(f"Removed network: {network.name}")
                        except docker.errors.APIError as e:
                            if "has active endpoints" in str(e):
                                print_warning(f"Network {network.name} has active endpoints, skipping")
                            else:
                                print_warning(f"Could not remove network {network.name}: {e}")
                        except Exception as e:
                            print_warning(f"Error removing network {network.name}: {e}")
                    
                    print_success("Docker networks cleaned")
                else:
                    print_info("No test networks found")
            except ImportError:
                print_warning("Docker Python library not available, skipping network cleanup")
            except Exception as e:
                print_warning(f"Failed to clean Docker networks: {e}")
                # Don't exit - network cleanup is not critical
        
        print_success("Cleaned certificates and cache")
