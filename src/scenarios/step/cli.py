"""
CLI command step executor.
"""

from typing import Any, Dict, Optional

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import CLIStep, StepDefaults
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class CLIStepExecutor(StepExecutor):
    """Executor for CLI command steps."""
    
    async def execute(
        self,
        step: CLIStep,
        ctx: RuntimeContext,
        defaults: Optional[StepDefaults] = None
    ) -> Dict[str, Any]:
        """Execute CLI command step."""
        # Substitute variables in command
        original_cmd = ctx.substitute(step.cli)
        cmd = original_cmd
        node_display = ctx.substitute(step.node) if step.node else "node1"
        
        # Log original command (before defaults)
        if self.debug:
            logger.info(f"CLI step: {original_cmd} (node: {node_display})")
        else:
            logger.info(f"CLI: {original_cmd}")
        
        # Apply CLI defaults if present
        if defaults and defaults.cli:
            from ...utils.cli_parser import get_cli_parser
            cli_parser = get_cli_parser()
            
            if self.debug:
                self._log_to_file(f"[DEBUG] Applying CLI defaults: {defaults.cli}")
                self._log_to_file(f"[DEBUG] Original command: {cmd}")
            
            # Substitute variables in CLI defaults
            cli_defaults = {
                key: ctx.substitute(value) 
                for key, value in defaults.cli.items()
            }
            
            # Apply defaults to command
            cmd_with_defaults = cli_parser.apply_cli_defaults(cmd, cli_defaults)
            
            if cmd_with_defaults and isinstance(cmd_with_defaults, str):
                cmd = cmd_with_defaults
        
        # Resolve node
        node = ctx.substitute(step.node) if step.node else "node1"
        
        # Execute command via container manager
        result = await self.container_manager.exec_cli_command(
            command=cmd,
            node=node,
            timeout=step.timeout
        )
        
        output = result["stdout"]
        exit_code = result["returncode"]
        
        # Check expectation FIRST - if command failed, don't try to extract data
        if step.expect == "success" and exit_code != 0:
            raise ScenarioExecutionError(
                f"CLI command failed: Expected success but got exit code {exit_code}",
                step=cmd[:100],
                context=result
            )
        elif step.expect == "error" and exit_code == 0:
            raise ScenarioExecutionError(
                f"CLI command succeeded: Expected error but got exit code 0",
                step=cmd[:100]
            )
        
        # Only extract data if command succeeded (exit_code == 0)
        # If command failed but we're not checking expectation, skip extraction
        if exit_code != 0:
            # Command failed - don't try to extract data from empty/failed output
            if step.save_node or step.save_hash or step.save_wallet or step.save_token:
                raise ScenarioExecutionError(
                    f"Cannot extract data from failed command (exit_code={exit_code}). "
                    f"Command output may be empty or invalid.",
                    step=cmd[:100],
                    context={"exit_code": exit_code, "stderr": result.get("stderr", "")[:500]}
                )
            # For save/save_to, save empty string or error message
            if step.save or step.save_to:
                variable_name = step.save or step.save_to
                ctx.set_variable(variable_name, result.get("stderr", "") or "")
                logger.debug("cli_step_saved_error", variable=variable_name)
            return result
        
        # Extract and save values if requested (only if command succeeded)
        from ..extractors import DataExtractor
        from ..schema import ExtractType
        
        if step.save_node:
            pattern = DataExtractor.get_default_pattern(ExtractType.NODE_ADDRESS)
            node_addr, error = DataExtractor.extract_and_validate(
                output, pattern, ExtractType.NODE_ADDRESS, required=True
            )
            if node_addr:
                ctx.set_variable(step.save_node, node_addr)
                logger.debug("cli_step_saved_node", variable=step.save_node, value=node_addr)
            else:
                raise ScenarioExecutionError(
                    f"Failed to extract node address from output: {error}",
                    step=cmd[:100],
                    context={"output": output[:500]}
                )
        
        if step.save_hash:
            pattern = DataExtractor.get_default_pattern(ExtractType.HASH)
            hash_value, error = DataExtractor.extract_and_validate(
                output, pattern, ExtractType.HASH, required=True
            )
            if hash_value:
                ctx.set_variable(step.save_hash, hash_value)
                logger.debug("cli_step_saved_hash", variable=step.save_hash, value=hash_value)
            else:
                # Log full output for debugging hash extraction failures
                logger.error("hash_extraction_failed",
                          variable=step.save_hash,
                          error=error,
                          output_preview=output[:1000],
                          command=cmd[:200])
                raise ScenarioExecutionError(
                    f"Failed to extract hash from output: {error}",
                    step=cmd[:100],
                    context={"output": output[:1000], "pattern": pattern}
                )
        
        if step.save_wallet:
            pattern = DataExtractor.get_default_pattern(ExtractType.WALLET_ADDRESS)
            wallet_addr, error = DataExtractor.extract_and_validate(
                output, pattern, ExtractType.WALLET_ADDRESS, required=True
            )
            if wallet_addr:
                ctx.set_variable(step.save_wallet, wallet_addr)
                logger.debug("cli_step_saved_wallet", variable=step.save_wallet, value=wallet_addr)
            else:
                raise ScenarioExecutionError(
                    f"Failed to extract wallet address from output: {error}",
                    step=cmd[:100],
                    context={"output": output[:500]}
                )
        
        if step.save_token:
            pattern = DataExtractor.get_default_pattern(ExtractType.TOKEN_NAME)
            token_ticker, error = DataExtractor.extract_and_validate(
                output, pattern, ExtractType.TOKEN_NAME, required=True
            )
            if token_ticker:
                ctx.set_variable(step.save_token, token_ticker)
                logger.debug("cli_step_saved_token", variable=step.save_token, value=token_ticker)
            else:
                raise ScenarioExecutionError(
                    f"Failed to extract token ticker from output: {error}",
                    step=cmd[:100],
                    context={"output": output[:500]}
                )
        
        # Save raw output if requested
        if step.save or step.save_to:
            variable_name = step.save or step.save_to
            ctx.set_variable(variable_name, output.strip())
            logger.debug("cli_step_saved", variable=variable_name)
        
        # Record success result
        ctx.add_result("CLI", True, {
            "command": cmd,
            "node": node,
            "exit_code": exit_code
        })
        
        return result

