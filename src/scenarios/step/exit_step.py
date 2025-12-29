"""Exit step for explicitly terminating scenario execution with error code."""

from typing import Dict, Any
from ..schema import ExitStep
from ..executor import RuntimeContext, ScenarioExecutionError
import structlog

logger = structlog.get_logger(__name__)


class ExitStepExecutor:
    """Executor for exit steps."""
    
    def __init__(self):
        self.logger = logger
    
    async def execute(self, step: ExitStep, ctx: RuntimeContext) -> Dict[str, Any]:
        """Execute exit step - terminate scenario with specified exit code.
        
        Args:
            step: Exit step to execute
            ctx: Execution context with variables
            
        Raises:
            ScenarioExecutionError: Always raised to terminate scenario
            
        Returns:
            Never returns - always raises exception
        """
        # Substitute variables in message if provided
        message = ctx.substitute(step.message) if step.message else f"Scenario terminated with exit code {step.exit}"
        
        # Log the exit
        if step.exit == 0:
            self.logger.info("exit_step_success", code=step.exit, message=message)
            print(f"✅ {message}")
        else:
            self.logger.error("exit_step_failure", code=step.exit, message=message)
            print(f"❌ {message}")
        
        # Raise error to terminate scenario
        raise ScenarioExecutionError(
            f"Scenario terminated with exit code {step.exit}: {message}",
            step=f"exit: {step.exit}",
            context={"exit_code": step.exit, "message": message}
        )

