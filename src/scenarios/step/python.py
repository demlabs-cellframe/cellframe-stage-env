"""
Python code step executor.
"""

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import PythonStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class PythonStepExecutor(StepExecutor):
    """Executor for Python code steps."""
    
    async def execute(self, step: PythonStep, ctx: RuntimeContext) -> None:
        """Execute Python code step."""
        try:
            # Create execution namespace with context
            namespace = {
                'ctx': ctx,
                '__builtins__': __builtins__,
            }
            
            # Execute Python code
            exec(step.python, namespace)
            
            # If save is specified and result is in namespace
            if step.save and 'result' in namespace:
                ctx.set_variable(step.save, namespace['result'])
                logger.debug("python_step_saved", variable=step.save, value=namespace['result'])
                
        except Exception as e:
            raise ScenarioExecutionError(
                f"Python step failed: {str(e)}",
                step=step.python[:100],
                context={'error': str(e)}
            )

