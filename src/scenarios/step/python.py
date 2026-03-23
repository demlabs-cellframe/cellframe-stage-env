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
            
            if (step.save or step.save_map) and 'result' in namespace:
                output = str(namespace['result']) if not isinstance(namespace['result'], str) else namespace['result']
                resolved_save = ctx.substitute(step.save) if step.save else None
                ctx.save_output(output, resolved_save, step.save_regex, step.save_map)
                
        except Exception as e:
            raise ScenarioExecutionError(
                f"Python step failed: {str(e)}",
                step=step.python[:100],
                context={'error': str(e)}
            )

