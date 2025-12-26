"""
Snapshot step executor.

Manages snapshot creation/restoration via scenario steps:
  - snapshot: create
    name: phase1
    
  - snapshot: restore
    name: phase1
"""

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import SnapshotStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class SnapshotStepExecutor(StepExecutor):
    """Executor for snapshot steps."""
    
    def __init__(self, container_manager, log_file=None, debug: bool = False, compose_manager=None):
        """Initialize snapshot executor."""
        super().__init__(container_manager, log_file, debug)
        self.compose_manager = compose_manager
    
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
        """Create snapshot."""
        # Stop containers if requested (default: true for consistent state)
        if step.stop_containers and self.compose_manager:
            logger.info("stopping_containers_for_snapshot")
            self.compose_manager.kill(timeout=10)  # docker compose stop - graceful stop without removal
        
        result = await manager.create_snapshot(name)
        if not result:
            raise RuntimeError(f"Failed to create snapshot: {name}")
        
        # Mark as base topology snapshot if requested
        if step.is_base:
            # Store marker for suite loader
            if hasattr(manager, 'snapshot') and manager.snapshot:
                marker_path = manager.snapshot.snapshots_path / f"{name}.base"
                marker_path.write_text(f"topology={ctx.variables.get('topology_name', 'default')}\n")
                logger.info("base_snapshot_marker_created", name=name)
        
        # Restart containers after snapshot if requested (default: true for sequential runs)
        if step.restart_after and self.compose_manager:
            logger.info("restarting_containers_after_snapshot")
            self.compose_manager.up(detach=True)
    
    async def _execute_restore(
        self, 
        step: SnapshotStep, 
        name: str, 
        manager, 
        ctx: RuntimeContext
    ) -> None:
        """Restore snapshot."""
        # CRITICAL: Stop containers BEFORE restore to prevent data corruption
        # Containers must not be writing to files while rsync copies data
        if step.stop_containers and self.compose_manager:
            logger.info("stopping_containers_before_restore")
            self.compose_manager.kill(timeout=30)  # Give 30s for graceful shutdown
        
        # Pre-cleanup to handle root-owned files from containers
        if self.container_manager:
            try:
                if hasattr(manager, 'snapshot') and manager.snapshot:
                    cache_path = manager.snapshot.cache_path
                    data_path = cache_path / "data"
                    configs_path = cache_path / "configs"
                    
                    if data_path.exists():
                        logger.info("pre_cleaning_data", path=str(data_path))
                        self.container_manager.cleanup_volume(str(data_path))
                    
                    if configs_path.exists():
                        logger.info("pre_cleaning_configs", path=str(configs_path))
                        self.container_manager.cleanup_volume(str(configs_path))
            except Exception as e:
                logger.warning("pre_restore_cleanup_failed", error=str(e))
        
        result = await manager.restore_snapshot(name)
        if not result:
            raise RuntimeError(f"Failed to restore snapshot: {name}")
    
    async def _execute_verify(
        self, 
        step: SnapshotStep, 
        name: str, 
        manager, 
        ctx: RuntimeContext
    ) -> None:
        """Verify snapshot exists and is valid."""
        if hasattr(manager, 'snapshot') and manager.snapshot:
            snapshots_path = manager.snapshot.snapshots_path
            
            # Check for snapshot in various formats
            exists = any([
                (snapshots_path / name).exists(),  # Directory
                (snapshots_path / f"{name}.sqfs").exists(),  # SquashFS
                (snapshots_path / f"{name}.marker").exists(),  # Marker
            ])
            
            if not exists:
                raise RuntimeError(f"Snapshot not found: {name}")
            
            logger.info("snapshot_verified", name=name)
        else:
            logger.warning("snapshot_verify_skipped_no_handler")
    
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


