"""
Bash script step executor.
"""

from typing import Any, Dict

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import BashStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class BashStepExecutor(StepExecutor):
    """Executor for Bash script steps."""
    
    async def execute(self, step: BashStep, ctx: RuntimeContext) -> Dict[str, Any]:
        """Execute Bash script step."""
        # Substitute variables in bash script
        script = ctx.substitute(step.bash)
        
        # Execute via container manager
        result = await self.container_manager.exec_bash_command(
            script=script,
            node=step.node,
            timeout=step.timeout
        )
        
        # Save result if requested
        if step.save:
            ctx.set_variable(step.save, result["stdout"])
            logger.debug("bash_step_saved", variable=step.save)
        
        # Check expectation
        if step.expect == "success" and result["returncode"] != 0:
            raise ScenarioExecutionError(
                f"Bash step failed: Expected success but got exit code {result['returncode']}",
                step=script[:100],
                context=result
            )
        elif step.expect == "error" and result["returncode"] == 0:
            raise ScenarioExecutionError(
                f"Bash step failed: Expected error but got success",
                step=script[:100],
                context=result
            )
        
        return result

