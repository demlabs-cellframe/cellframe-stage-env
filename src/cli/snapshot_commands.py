"""
CLI commands for snapshot management.
"""
import typer
from pathlib import Path
from typing import Callable, Optional

from .common import print_info, print_success, print_error, print_warning
from src.utils.i18n import _


def register_commands(app: typer.Typer, base_path: Path, get_config_path: Callable[[], Optional[Path]]):
    """Register snapshot management commands."""
    
    @app.command()
    def snapshots_list():
        """📦 List all available topology snapshots."""
        from ..snapshots import TopologySnapshotManager
        from ..snapshots.utils import format_size
        from rich.table import Table
        from rich.console import Console
        
        cache_dir = base_path / "cache"
        snapshot_mgr = TopologySnapshotManager(cache_dir)
        
        snapshots = snapshot_mgr.list_snapshots()
        
        if not snapshots:
            print_info(_("No snapshots found"))
            return
        
        console = Console()
        table = Table(title=_("📦 Topology Snapshots"))
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
        print_info(_("Total snapshot size: {}").format(format_size(total_size)))
    
    @app.command()
    def snapshots_delete(
        topology_hash: str = typer.Argument(..., help="Topology hash to delete (or 'all' for all snapshots)"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ):
        """🗑️  Delete topology snapshot(s)."""
        from ..snapshots import TopologySnapshotManager
        from rich.prompt import Confirm
        
        cache_dir = base_path / "cache"
        snapshot_mgr = TopologySnapshotManager(cache_dir)
        
        if topology_hash.lower() == "all":
            if not yes:
                if not Confirm.ask(_("Delete ALL snapshots?"), default=False):
                    print_info(_("Cancelled"))
                    return
            
            deleted = snapshot_mgr.delete_all()
            print_success(_("Deleted {} snapshot(s)").format(deleted))
        else:
            if not yes:
                if not Confirm.ask(_("Delete snapshot {}?").format(topology_hash), default=False):
                    print_info(_("Cancelled"))
                    return
            
            if snapshot_mgr.delete_snapshot(topology_hash):
                print_success(_("Deleted snapshot {}").format(topology_hash))
            else:
                print_error(_("Snapshot {} not found").format(topology_hash))
                raise typer.Exit(1)
    
    @app.command()
    def snapshots_info(
        topology_hash: str = typer.Argument(..., help="Topology hash"),
    ):
        """ℹ️  Show detailed snapshot information."""
        from ..snapshots import TopologySnapshotManager
        from ..snapshots.utils import format_size
        from rich.panel import Panel
        from rich.console import Console
        
        cache_dir = base_path / "cache"
        snapshot_mgr = TopologySnapshotManager(cache_dir)
        
        info = snapshot_mgr.get_snapshot_info(topology_hash)
        
        if not info:
            print_error(_("Snapshot {} not found").format(topology_hash))
            raise typer.Exit(1)
        
        console = Console()
        
        content = [
            _("Topology Hash: {}").format(info['topology_hash']),
            _("Created: {}").format(info['created']),
            _("Modified: {}").format(info.get('modified', 'N/A')),
            _("Version: {}").format(info['version']),
            _("Node Count: {}").format(info['node_count']),
            _("Consensus: {}").format(info['consensus_type']),
            _("Network: {}").format(info.get('network', 'stagenet')),
            _("Size: {}").format(format_size(info['size_bytes'])),
            _("Valid: {}").format(_("✅ Yes") if info['valid'] else _("❌ No")),
        ]
        
        if 'nodes' in info:
            content.append("\n" + _("Nodes: {}").format(', '.join(info['nodes'])))
        
        panel = Panel(
            "\n".join(content),
            title=_("📦 Snapshot Information"),
            border_style="cyan"
        )
        console.print(panel)
    
    @app.command()
    def snapshots_clean(
        older_than_days: int = typer.Option(30, "--older-than", help="Delete snapshots older than N days"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ):
        """🧹 Clean old snapshots."""
        from ..snapshots import TopologySnapshotManager
        from ..snapshots.utils import format_size
        from rich.prompt import Confirm
        import time
        
        cache_dir = base_path / "cache"
        snapshot_mgr = TopologySnapshotManager(cache_dir)
        
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
            print_info(_("No snapshots older than {} days").format(older_than_days))
            return
        
        print_info(_("Found {} snapshot(s) older than {} days").format(len(old_snapshots), older_than_days))
        print_info(_("Total size: {}").format(format_size(total_size)))
        
        if not yes:
            if not Confirm.ask(_("Delete these snapshots?"), default=False):
                print_info(_("Cancelled"))
                return
        
        deleted = 0
        for snapshot in old_snapshots:
            if snapshot_mgr.delete_snapshot(snapshot['topology_hash']):
                deleted += 1
        
        print_success(_("Deleted {} snapshot(s), freed {}").format(deleted, format_size(total_size)))

