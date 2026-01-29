"""
Print step executor for debugging.
"""

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import PrintStep
from ..executor import RuntimeContext

logger = get_logger(__name__)


class PrintStepExecutor(StepExecutor):
    """Executor for print steps (debugging output)."""
    
    async def execute(self, step: PrintStep, ctx: RuntimeContext) -> None:
        """Execute print step."""
        # Substitute variables in message
        message = ctx.substitute(step.print)
        
        # Print to logger (will appear in test output)
        print(message)
        logger.info(f"Print: {message}")
        
        ctx.add_result("print", True, {"message": message})
