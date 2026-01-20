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
            
            # Check conditions - substitute variables in expected values
            # All string comparisons are case-insensitive
            output_lower = output.lower()
            
            if check.contains:
                expected = ctx.substitute(check.contains)
                if expected.lower() not in output_lower:
                    raise ScenarioExecutionError(
                        f"CLI check failed: expected '{expected}' in output\n"
                        f"Got: {output}"
                    )
            
            if check.not_contains:
                not_expected = ctx.substitute(check.not_contains)
                if not_expected.lower() in output_lower:
                    raise ScenarioExecutionError(
                        f"CLI check failed: '{not_expected}' should not be in output\n"
                        f"Got: {output}"
                    )
            
            if check.equals:
                expected_equals = ctx.substitute(check.equals)
                if output.strip() != expected_equals:
                    raise ScenarioExecutionError(
                        f"CLI check failed: expected exact match\n"
                        f"Expected: {expected_equals}\n"
                        f"Got: {output}"
                    )
            
            ctx.add_result("check_cli", True, {"command": cmd})
            
        except subprocess.TimeoutExpired:
            ctx.add_result("check_cli", False, {"command": cmd, "error": "timeout"})
            raise ScenarioExecutionError(f"CLI check timeout: {cmd}")

