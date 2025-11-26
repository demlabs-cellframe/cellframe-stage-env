"""
Python check executor.
"""

from ...utils.logger import get_logger
from .base import CheckExecutor
from ..schema import PythonCheck
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class PythonCheckExecutor(CheckExecutor):
    """Executor for Python checks."""
    
    async def execute(self, check: PythonCheck, ctx: RuntimeContext) -> None:
        """Execute Python check."""
        logger.debug("Executing Python check")
        
        try:
            # Create execution namespace with context
            namespace = {
                'ctx': ctx,
                '__builtins__': __builtins__,
            }
            
            # Execute Python code - should raise AssertionError if check fails
            exec(check.python, namespace)
            
            ctx.add_result("check_python", True, {"check": "Python check"})
            
        except AssertionError as e:
            ctx.add_result("check_python", False, {"error": str(e)})
            raise ScenarioExecutionError(f"Python check failed: {str(e)}")
        except Exception as e:
            ctx.add_result("check_python", False, {"error": str(e)})
            raise ScenarioExecutionError(f"Python check error: {str(e)}")

