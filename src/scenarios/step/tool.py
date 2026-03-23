"""
Cellframe-node-tool command step executor.
"""

from typing import Any, Dict

from ...utils.logger import get_logger
from .base import StepExecutor, resolve_timeout
from ..schema import ToolStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class ToolStepExecutor(StepExecutor):
    """Executor for cellframe-node-tool command steps."""
    
    async def execute(self, step: ToolStep, ctx: RuntimeContext) -> Dict[str, Any]:
        """Execute cellframe-node-tool command step."""
        tool_cmd = ctx.substitute(step.tool)
        node = ctx.substitute(step.node) if step.node else step.node
        
        timeout = resolve_timeout(step.timeout, ctx, default=30)
        result = await self.container_manager.exec_tool_command(
            tool_cmd=tool_cmd,
            node=node,
            timeout=timeout
        )
        
        # Log tool execution
        self._log_to_file("\n" + "=" * 70)
        self._log_to_file("TOOL COMMAND")
        self._log_to_file("=" * 70)
        self._log_to_file(f"Node: {step.node}")
        self._log_to_file(f"Command: cellframe-node-tool {tool_cmd}")
        self._log_to_file(f"Timeout: {timeout}s")
        self._log_to_file(f"Expected: {step.expect}")
        self._log_to_file("\n--- Tool Response ---")
        self._log_to_file(f"Exit Code: {result['returncode']}\n")
        if result["stdout"]:
            self._log_to_file(f"Stdout:\n{result['stdout']}")
        if result["stderr"]:
            self._log_to_file(f"Stderr:\n{result['stderr']}")
        self._log_to_file("\n" + "=" * 70 + "\n")
        
        if step.save or step.save_map:
            resolved_save = ctx.substitute(step.save) if step.save else None
            ctx.save_output(result["stdout"], resolved_save, step.save_regex, step.save_map)
            if resolved_save:
                self._log_to_file(f"✓ Saved to variable: {resolved_save}")
        
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

