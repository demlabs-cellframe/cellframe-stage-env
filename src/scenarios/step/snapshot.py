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
                # CRITICAL: Before creating snapshot, save token_hash as static_genesis_event
                # This ensures the snapshot includes the genesis event hash in configs
                
                # Check for token_hash (current) or token_hash_final (legacy)
                token_hash = None
                if 'token_hash' in ctx.variables:
                    token_hash = ctx.variables['token_hash']
                elif 'token_hash_final' in ctx.variables:
                    token_hash = ctx.variables['token_hash_final']
                
                if token_hash and hasattr(ctx, 'genesis_config_manager'):
                    logger.info("saving_token_hash_to_config_before_snapshot",
                              hash=token_hash[:16],
                              note="Writing static_genesis_event to configs before snapshot creation")
                    
                    # Get node configs from context
                    if hasattr(ctx, 'node_configs'):
                        await ctx.genesis_config_manager.update_static_genesis_in_config(
                            chain_name="zerochain",
                            genesis_hash=token_hash,
                            node_configs=ctx.node_configs
                        )
                        logger.info("static_genesis_event_saved_before_snapshot",
                                  hash=token_hash[:16])
                    else:
                        logger.warning("node_configs_not_in_context",
                                     note="Cannot save static_genesis_event without node configs")
                else:
                    # FAIL FAST: If we are creating a genesis snapshot but don't have the token hash,
                    # the snapshot will be useless for genesis.
                    logger.error("token_hash_missing_for_genesis_snapshot",
                               variables_keys=list(ctx.variables.keys())[:20],
                               has_genesis_manager=hasattr(ctx, 'genesis_config_manager'),
                               note="Cannot create valid genesis snapshot without token_hash")
                    raise RuntimeError(f"Cannot create genesis snapshot '{snapshot_name}': token_hash not found in context. "
                                     "Ensure token declaration step was successful and 'save_hash' was used.")
                
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


