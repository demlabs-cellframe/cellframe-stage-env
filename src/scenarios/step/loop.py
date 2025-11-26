"""
Loop step executor.
"""

from typing import Optional

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import LoopStep, StepDefaults
from ..executor import RuntimeContext

logger = get_logger(__name__)


class LoopStepExecutor(StepExecutor):
    """Executor for loop steps."""
    
    def __init__(
        self,
        container_manager,
        log_file=None,
        debug: bool = False,
        execute_steps_callback=None
    ):
        """
        Initialize loop executor.
        
        Args:
            container_manager: Docker container manager
            log_file: Optional log file
            debug: Debug mode
            execute_steps_callback: Callback to execute steps (needs executor reference)
        """
        super().__init__(container_manager, log_file, debug)
        self.execute_steps_callback = execute_steps_callback
    
    async def execute(
        self,
        step: LoopStep,
        ctx: RuntimeContext,
        defaults: Optional[StepDefaults] = None
    ) -> None:
        """Execute loop step."""
        logger.info(f"Starting loop: {step.loop} iterations")
        
        if not self.execute_steps_callback:
            raise RuntimeError("execute_steps_callback not set for LoopStepExecutor")
        
        for i in range(step.loop):
            logger.debug(f"Loop iteration {i+1}/{step.loop}")
            ctx.set_variable("i", i)
            ctx.set_variable("iteration", i + 1)
            
            await self.execute_steps_callback(step.steps, ctx, defaults)
        
        ctx.add_result("loop", True, {"iterations": step.loop})

