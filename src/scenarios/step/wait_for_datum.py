"""
Wait-for-datum step executor.
"""

from typing import List

from ...utils.logger import get_logger
from ...monitoring import MonitoringManager
from .base import StepExecutor
from ..schema import WaitForDatumStep, DatumStatus
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class WaitForDatumStepExecutor(StepExecutor):
    """Executor for wait-for-datum steps."""
    
    def __init__(
        self,
        container_manager,
        log_file=None,
        debug: bool = False,
        node_cli_path: str = "cellframe-node-cli"
    ):
        """Initialize wait-for-datum executor."""
        super().__init__(container_manager, log_file, debug)
        self.node_cli_path = node_cli_path
    
    async def execute(self, step: WaitForDatumStep, ctx: RuntimeContext) -> None:
        """Execute wait-for-datum step."""
        # Support both single hash and list of hashes
        datum_hashes = step.wait_for_datum if isinstance(step.wait_for_datum, list) else [step.wait_for_datum]
        
        # Substitute variables in hashes
        datum_hashes = [ctx.substitute(h) for h in datum_hashes]
        
        logger.info(f"Monitoring {len(datum_hashes)} datum(s)")
        
        # Get monitoring manager singleton
        monitoring = MonitoringManager.get_instance(
            node_cli_path=self.node_cli_path,
            log_file=self.log_file
        )
        
        # Monitor each datum directly (no background tasks)
        results = []
        for datum_hash in datum_hashes:
            logger.debug(f"Monitoring datum: {datum_hash[:16]}...")
            
            # Substitute variables in parameters
            node = ctx.substitute(step.node) if step.node else None
            network = ctx.substitute(step.network) if step.network else "stagenet"
            chain = ctx.substitute(step.chain) if step.chain else None
            
            # Wait for datum to complete processing
            result = await monitoring.datum.wait_for_datum(
                datum_hash=datum_hash,
                node=node,
                network=network,
                chain=chain,
                check_master_nodes=step.check_master_nodes,
                timeout_total=step.timeout_total,
                timeout_mempool=step.timeout_mempool,
                timeout_verification=step.timeout_verification,
                timeout_in_blocks=step.timeout_in_blocks
            )
            
            results.append(result)
            
            # Check if monitoring failed
            if result.status != DatumStatus.SUCCESS:
                error_msg = f"Datum monitoring failed: {result.error_message}"
                logger.error(error_msg)
                
                # Log to scenario file
                if self.log_file:
                    self._log_to_file(f"\n{'=' * 80}\n")
                    self._log_to_file(f"❌ WAIT_FOR_DATUM FAILED\n")
                    self._log_to_file(f"Datum: {datum_hash}\n")
                    self._log_to_file(f"Status: {result.status.value}\n")
                    self._log_to_file(f"Error: {result.error_message}\n")
                    self._log_to_file(f"Elapsed: {result.elapsed_time:.1f}s\n")
                    self._log_to_file(f"Details: {result.details}\n")
                    self._log_to_file(f"{'=' * 80}\n\n")
                
                raise ScenarioExecutionError(
                    error_msg,
                    step=step,
                    context={
                        "datum_hash": datum_hash,
                        "status": result.status.value,
                        "elapsed_time": result.elapsed_time,
                        "details": result.details
                    }
                )
            
            logger.info(f"✅ Datum {datum_hash[:16]}... monitored successfully: {result.status.value} in {result.elapsed_time:.1f}s")
        
        # Save status to variable if requested
        if step.save_status:
            if len(results) == 1:
                ctx.set_variable(step.save_status, results[0].status.value)
            else:
                ctx.set_variable(step.save_status, [r.status.value for r in results])
        
        # Add to context results
        ctx.add_result(
            "wait_for_datum",
            True,
            {
                "datum_count": len(datum_hashes),
                "results": [
                    {
                        "hash": r.datum_hash,
                        "status": r.status.value,
                        "elapsed": r.elapsed_time,
                        "details": r.details
                    }
                    for r in results
                ]
            }
        )

