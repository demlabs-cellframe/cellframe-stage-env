"""
CLI check executor.
"""

import subprocess

from ...utils.logger import get_logger
from .base import CheckExecutor
from ..schema import CLICheck
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class CLICheckExecutor(CheckExecutor):
    """Executor for CLI checks."""
    
    async def execute(self, check: CLICheck, ctx: RuntimeContext) -> None:
        """Execute CLI check."""
        cmd = ctx.substitute(check.cli)
        logger.debug(f"Checking CLI: {cmd}")
        
        try:
            result = await self.container_manager.exec_cli_command(
                command=cmd,
                node=check.node,
                timeout=check.timeout
            )
            output = result["stdout"]
            
            # Check conditions
            if check.contains and check.contains not in output:
                raise ScenarioExecutionError(
                    f"CLI check failed: expected '{check.contains}' in output\n"
                    f"Got: {output}"
                )
            
            if check.not_contains and check.not_contains in output:
                raise ScenarioExecutionError(
                    f"CLI check failed: '{check.not_contains}' should not be in output\n"
                    f"Got: {output}"
                )
            
            if check.equals and output.strip() != check.equals:
                raise ScenarioExecutionError(
                    f"CLI check failed: expected exact match\n"
                    f"Expected: {check.equals}\n"
                    f"Got: {output}"
                )
            
            ctx.add_result("check_cli", True, {"command": cmd})
            
        except subprocess.TimeoutExpired:
            ctx.add_result("check_cli", False, {"command": cmd, "error": "timeout"})
            raise ScenarioExecutionError(f"CLI check timeout: {cmd}")

