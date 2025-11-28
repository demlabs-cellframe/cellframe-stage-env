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


