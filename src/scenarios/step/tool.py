"""
Cellframe-node-tool command step executor.
"""

from typing import Any, Dict

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import ToolStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class ToolStepExecutor(StepExecutor):
    """Executor for cellframe-node-tool command steps."""
    
    async def execute(self, step: ToolStep, ctx: RuntimeContext) -> Dict[str, Any]:
        """Execute cellframe-node-tool command step."""
        # Substitute variables in tool command
        tool_cmd = ctx.substitute(step.tool)
        
        # Execute via container manager
        result = await self.container_manager.exec_tool_command(
            tool_cmd=tool_cmd,
            node=step.node,
            timeout=step.timeout
        )
        
        # Log tool execution
        self._log_to_file("\n" + "=" * 70)
        self._log_to_file("TOOL COMMAND")
        self._log_to_file("=" * 70)
        self._log_to_file(f"Node: {step.node}")
        self._log_to_file(f"Command: cellframe-node-tool {tool_cmd}")
        self._log_to_file(f"Timeout: {step.timeout}s")
        self._log_to_file(f"Expected: {step.expect}")
        self._log_to_file("\n--- Tool Response ---")
        self._log_to_file(f"Exit Code: {result['returncode']}\n")
        if result["stdout"]:
            self._log_to_file(f"Stdout:\n{result['stdout']}")
        if result["stderr"]:
            self._log_to_file(f"Stderr:\n{result['stderr']}")
        self._log_to_file("\n" + "=" * 70 + "\n")
        
        # Save result if requested
        if step.save:
            ctx.set_variable(step.save, result["stdout"].strip())
            self._log_to_file(f"✓ Saved to variable: {step.save}")
            logger.debug("tool_step_saved", variable=step.save)
        
        # Check expectation
        if step.expect == "success" and result["returncode"] != 0:
            raise ScenarioExecutionError(
                f"Tool command failed: Expected success but got exit code {result['returncode']}",
                step=f"cellframe-node-tool {tool_cmd}",
                context=result
            )
        elif step.expect == "error" and result["returncode"] == 0:
            raise ScenarioExecutionError(
                f"Tool command succeeded: Expected error but got exit code 0",
                step=f"cellframe-node-tool {tool_cmd}"
            )
        
        return result

