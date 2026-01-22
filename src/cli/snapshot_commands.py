"""
CLI commands for snapshot management.

Snapshots allow you to save and restore network state for fast test iteration.
"""
import typer
from pathlib import Path
from typing import Callable, Optional

from .common import print_info, print_success, print_error, print_warning


SNAPSHOTS_HELP = """
📦 SNAPSHOT MANAGEMENT
━━━━━━━━━━━━━━━━━━━━━━

Snapshots save the complete network state (data + configs) allowing fast restore.

🔧 COMMANDS:
  snapshots-list      List all available snapshots
  snapshots-create    Create a new snapshot of current state
  snapshots-info      Show detailed snapshot information
  snapshots-delete    Delete snapshot(s)
  snapshots-clean     Remove old snapshots (default: >30 days)
  restore             Restore network from a snapshot

📝 EXAMPLES:

  # List all snapshots
  ./stage-env snapshots-list

  # Create snapshot after setup
  ./stage-env snapshots-create after_wallet_setup

  # Create snapshot without stopping network (not recommended)
  ./stage-env snapshots-create quick_save --no-stop

  # Restore to a previous state
  ./stage-env restore after_wallet_setup

  # Show snapshot details
  ./stage-env snapshots-info clean_state

  # Delete specific snapshot
  ./stage-env snapshots-delete old_snapshot

  # Delete all snapshots
  ./stage-env snapshots-delete all --yes

  # Clean snapshots older than 7 days
  ./stage-env snapshots-clean --older-than 7

🔄 TYPICAL WORKFLOW:

  1. Start network:     ./stage-env start
  2. Run some tests:    ./stage-env run-tests tests/functional/wallet
  3. Create checkpoint: ./stage-env snapshots-create checkpoint1
  4. Run more tests:    ./stage-env run-tests tests/functional/token
  5. Something broke?   ./stage-env restore checkpoint1

⚙️  CONFIGURATION (stage-env.cfg):

  [suite_isolation]
  mode = filesystem          # filesystem, squashfs, recreate, disabled
  snapshot_name = clean_state
  snapshots_dir = ../testing/snapshots

💡 TIPS:
  • Always stop network before creating snapshots (--stop is default)
  • 'clean_state' snapshot is created automatically after genesis
  • 'phase1_zerochain' snapshot saves state after Phase 1 genesis
  • Snapshots include: node data, configs, certificates, genesis state
"""


def register_commands(app: typer.Typer, base_path: Path, get_config_path: Callable[[], Optional[Path]]):
    """Register snapshot management commands."""
    
    def _get_snapshots_dir() -> Path:
        """Get snapshots directory from config or default."""
        from ..config.loader import ConfigLoader
        try:
            config_loader = ConfigLoader(base_path)
            config = config_loader.load()
            snapshots_dir = config.get('snapshots_dir', '../testing/snapshots')
            return (base_path / snapshots_dir).resolve()
        except Exception:
            return base_path.parent / "testing" / "snapshots"
    
    @app.command()
    def snapshots_help():
        """❓ Show detailed help about snapshot management."""
        from rich.console import Console
        from rich.markdown import Markdown
        
        console = Console()
        console.print(SNAPSHOTS_HELP)
    
    @app.command()
    def snapshots_list():
        """📦 List all available snapshots with size and status."""
        from ..snapshots import TopologySnapshotManager
        from ..snapshots.utils import format_size
        from rich.table import Table
        from rich.console import Console
        
        snapshots_dir = _get_snapshots_dir()
        snapshot_mgr = TopologySnapshotManager(snapshots_dir)
        
        snapshots = snapshot_mgr.list_snapshots()
        
        if not snapshots:
            print_info("No snapshots found")
            return
        
        console = Console()
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
        print_info(f"Total snapshot size: {format_size(total_size)}")
    
    @app.command()
    def snapshots_create(
        name: str = typer.Argument(..., help="Snapshot name (e.g., 'my_checkpoint', 'after_token_creation')"),
        stop_network: bool = typer.Option(True, "--stop/--no-stop", help="Stop network before snapshot (recommended for consistency)"),
    ):
        """📸 Create snapshot of current network state. Stops network, saves data+configs, restarts."""
        import asyncio
        from ..network.manager import NetworkManager
        from ..snapshots.utils import format_size
        
        print_info(f"📸 Creating snapshot: {name}")
        
        config_path = get_config_path()
        network_mgr = NetworkManager(base_path, config_path=config_path)
        
        async def _create_snapshot():
            if stop_network:
                print_info("⏸️  Stopping network for clean snapshot...")
                await network_mgr.stop(remove_volumes=False)
            
            result = await network_mgr.snapshot_manager.create_snapshot(name)
            
            if stop_network:
                print_info("▶️  Restarting network...")
                await network_mgr.start(rebuild=False, wait_ready=True)
            
            return result
        
        try:
            result = asyncio.run(_create_snapshot())
            
            if result:
                # Get snapshot info
                info = network_mgr.snapshot_manager.get_snapshot_info(name)
                if info:
                    print_success(f"✅ Snapshot '{name}' created ({format_size(info.get('size_bytes', 0))})")
                else:
                    print_success(f"✅ Snapshot '{name}' created")
            else:
                print_error(f"Failed to create snapshot '{name}'")
                raise typer.Exit(1)
        except Exception as e:
            print_error(f"Failed to create snapshot: {e}")
            raise typer.Exit(1)
    
    @app.command()
    def snapshots_delete(
        name: str = typer.Argument(..., help="Snapshot name to delete (or 'all' for all snapshots)"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    ):
        """🗑️  Delete snapshot by name. Use 'all' to remove all snapshots."""
        from ..snapshots import TopologySnapshotManager
        from rich.prompt import Confirm
        
        snapshots_dir = _get_snapshots_dir()
        snapshot_mgr = TopologySnapshotManager(snapshots_dir)
        
        if name.lower() == "all":
            if not yes:
                if not Confirm.ask("Delete ALL snapshots?", default=False):
                    print_info("Cancelled")
                    return
            
            deleted = snapshot_mgr.delete_all()
            print_success(f"Deleted {deleted} snapshot(s)")
        else:
            if not yes:
                if not Confirm.ask(f"Delete snapshot '{name}'?", default=False):
                    print_info("Cancelled")
                    return
            
            if snapshot_mgr.delete_snapshot(name):
                print_success(f"Deleted snapshot '{name}'")
            else:
                print_error(f"Snapshot '{name}' not found")
                raise typer.Exit(1)
    
    @app.command()
    def snapshots_info(
        name: str = typer.Argument(..., help="Snapshot name"),
    ):
        """ℹ️  Show detailed info: size, nodes, creation date, validity."""
        from ..snapshots import TopologySnapshotManager
        from ..snapshots.utils import format_size
        from rich.panel import Panel
        from rich.console import Console
        
        snapshots_dir = _get_snapshots_dir()
        snapshot_mgr = TopologySnapshotManager(snapshots_dir)
        
        info = snapshot_mgr.get_snapshot_info(name)
        
        if not info:
            print_error(f"Snapshot '{name}' not found")
            raise typer.Exit(1)
        
        console = Console()
        
        content = [
            f"Topology Hash: {info['topology_hash']}",
            f"Created: {info['created']}",
            f"Modified: {info.get('modified', 'N/A')}",
            f"Version: {info['version']}",
            f"Node Count: {info['node_count']}",
            f"Consensus: {info['consensus_type']}",
            f"Network: {info.get('network', 'stagenet')}",
            f"Size: {format_size(info['size_bytes'])}",
            f"Valid: {'✅ Yes' if info['valid'] else '❌ No'}",
        ]
        
        if 'nodes' in info:
            content.append(f"\nNodes: {', '.join(info['nodes'])}")
        
        panel = Panel(
            "\n".join(content),
            title="📦 Snapshot Information",
            border_style="cyan"
        )
        console.print(panel)
    
    @app.command()
    def snapshots_clean(
        older_than_days: int = typer.Option(30, "--older-than", help="Delete snapshots older than N days (default: 30)"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    ):
        """🧹 Remove old snapshots to free disk space. Default: older than 30 days."""
        from ..snapshots import TopologySnapshotManager
        from ..snapshots.utils import format_size
        from rich.prompt import Confirm
        import time
        
        snapshots_dir = _get_snapshots_dir()
        snapshot_mgr = TopologySnapshotManager(snapshots_dir)
        
        # Get old snapshots
        all_snapshots = snapshot_mgr.list_snapshots()
        cutoff_time = time.time() - (older_than_days * 86400)
        
        old_snapshots = []
        total_size = 0
        
        for snapshot in all_snapshots:
            # Parse created timestamp
            try:
                from datetime import datetime
                created_dt = datetime.fromisoformat(snapshot['created'].replace('Z', '+00:00'))
                created_ts = created_dt.timestamp()
                
                if created_ts < cutoff_time:
                    old_snapshots.append(snapshot)
                    total_size += snapshot.get('size_bytes', 0)
            except Exception:
                continue
        
        if not old_snapshots:
            print_info(f"No snapshots older than {older_than_days} days")
            return
        
        print_info(f"Found {len(old_snapshots)} snapshot(s) older than {older_than_days} days")
        print_info(f"Total size: {format_size(total_size)}")
        
        if not yes:
            if not Confirm.ask("Delete these snapshots?", default=False):
                print_info("Cancelled")
                return
        
        deleted = 0
        for snapshot in old_snapshots:
            if snapshot_mgr.delete_snapshot(snapshot['topology_hash']):
                deleted += 1
        
        print_success(f"Deleted {deleted} snapshot(s), freed {format_size(total_size)}")

