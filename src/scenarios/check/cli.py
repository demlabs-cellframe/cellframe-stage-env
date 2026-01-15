"""
CLI check executor.
"""

import subprocess
from typing import Optional

from ...utils.logger import get_logger
from .base import CheckExecutor
from ..schema import CLICheck, StepDefaults
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class CLICheckExecutor(CheckExecutor):
    """Executor for CLI checks."""
    
    async def execute(self, check: CLICheck, ctx: RuntimeContext, defaults: Optional[StepDefaults] = None) -> None:
        """Execute CLI check."""
        cmd = ctx.substitute(check.cli)
        
        # Apply CLI defaults if present (like -net from defaults.cli.net)
        if defaults and defaults.cli:
            from ...utils.cli_parser import get_cli_parser
            cli_parser = get_cli_parser()
            
            # Substitute variables in CLI defaults
            cli_defaults = {
                key: ctx.substitute(value) 
                for key, value in defaults.cli.items()
            }
            
            # Apply defaults to command
            cmd_with_defaults = cli_parser.apply_cli_defaults(cmd, cli_defaults)
            
            if cmd_with_defaults and isinstance(cmd_with_defaults, str):
                cmd = cmd_with_defaults
        
        node = ctx.substitute(check.node) if check.node else "node1"
        logger.debug(f"Checking CLI: {cmd} on {node}")
        
        try:
            result = await self.container_manager.exec_cli_command(
                command=cmd,
                node=node,
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

