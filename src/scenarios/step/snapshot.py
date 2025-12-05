"""
Snapshot step executor.
"""

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import SnapshotStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class SnapshotStepExecutor(StepExecutor):
    """Executor for snapshot steps."""
    
    async def execute(self, step: SnapshotStep, ctx: RuntimeContext) -> None:
        """Execute snapshot step."""
        logger.info(f"Snapshot operation: {step.snapshot} name={step.name}")
        
        # Substitute variables
        snapshot_name = ctx.substitute(step.name)
        operation = ctx.substitute(step.snapshot)
        phase = ctx.substitute(step.phase)
        
        # Get SnapshotManager - need to get it from context
        if not hasattr(ctx, 'snapshot_manager'):
            raise ScenarioExecutionError(
                "SnapshotManager not available in context. "
                "Snapshot operations require NetworkManager to be set in RuntimeContext.",
                step=step
            )
        
        snapshot_manager = ctx.snapshot_manager
        
        try:
            if operation == "create":
                # Note: Config updates (genesis hash, fee_addr) must be done via explicit ConfigStep
                # before calling snapshot create. This executor no longer handles implicit updates.
                
                result = await snapshot_manager.create_snapshot(snapshot_name)
                if not result:
                    raise RuntimeError("Snapshot creation failed")
            elif operation == "restore":
                # Pre-cleanup using Docker if available to handle root-owned files
                # This fixes "Operation not permitted" errors when rsync tries to overwrite
                # root-owned files created by Docker containers.
                if hasattr(self, 'container_manager') and self.container_manager:
                    try:
                        # Get cache path from snapshot implementation
                        if hasattr(snapshot_manager, 'snapshot') and snapshot_manager.snapshot:
                            cache_path = snapshot_manager.snapshot.cache_path
                            data_path = cache_path / "data"
                            configs_path = cache_path / "configs"
                            
                            if data_path.exists():
                                logger.info("pre_cleaning_data_volume", path=str(data_path))
                                self.container_manager.cleanup_volume(str(data_path))
                            
                            if configs_path.exists():
                                logger.info("pre_cleaning_configs_volume", path=str(configs_path))
                                self.container_manager.cleanup_volume(str(configs_path))
                    except Exception as cleanup_err:
                        logger.warning("pre_restore_cleanup_failed", error=str(cleanup_err))

                result = await snapshot_manager.restore_snapshot(snapshot_name)
                if not result:
                    raise RuntimeError("Snapshot restoration failed")
            elif operation == "verify":
                # Verify operation - would need to implement
                logger.warning("Snapshot verify operation not yet implemented")
            else:
                raise ScenarioExecutionError(f"Unknown snapshot operation: {operation}", step=step)
            
            logger.info(f"✅ Snapshot operation '{operation}' completed")
            ctx.add_result("snapshot", True, {"operation": operation, "name": snapshot_name})
            
        except Exception as e:
            error_msg = f"Snapshot operation failed: {str(e)}"
            logger.error(error_msg)
            ctx.add_result("snapshot", False, {"operation": operation, "error": str(e)})
            raise ScenarioExecutionError(error_msg, step=step)


