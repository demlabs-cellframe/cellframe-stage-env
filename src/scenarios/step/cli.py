"""
CLI command step executor.
"""

import asyncio
import json
from typing import Any, Dict, Optional

from ...utils.logger import get_logger
from .base import StepExecutor, resolve_timeout
from ..schema import CLIStep, StepDefaults
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class CLIStepExecutor(StepExecutor):
    """Executor for CLI command steps."""
    
    @staticmethod
    def _detect_cli_error(output: str) -> bool:
        """Check CLI output for error indicators.
        
        cellframe-node-cli always returns exit code 0 for successfully communicated
        commands, even if the command itself failed (the return code from the handler
        is not propagated to the process exit code). This method detects errors
        from the output content.
        
        Returns True if the output indicates a command failure.
        """
        if not output or not output.strip():
            return False
        
        # Try JSON parsing first
        try:
            data = json.loads(output)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                # Check for JSON-RPC errors array
                if 'errors' in item:
                    errors = item['errors']
                    if isinstance(errors, list) and len(errors) > 0:
                        return True
                    if isinstance(errors, dict):
                        if errors.get('code', -1) != 0:
                            return True
                # Check "transfer": "False" pattern (tx_create failure indicator)
                if item.get('transfer') == 'False':
                    return True
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        
        # YAML-like format (cellframe CLI often outputs in this format)
        try:
            import yaml
            data = yaml.safe_load(output)
            if isinstance(data, dict):
                if 'errors' in data:
                    errors = data['errors']
                    if isinstance(errors, dict) and errors.get('code', -1) != 0:
                        return True
                    if isinstance(errors, list) and len(errors) > 0:
                        return True
                if data.get('transfer') == 'False':
                    return True
        except Exception:
            pass
        
        # Regex-based error pattern detection (fallback for YAML/JSON parsing issues)
        # cellframe-node-cli outputs errors in YAML-like format with indentation:
        #   errors:
        #     code: 32
        #     message: ...
        # The blank lines and indentation may confuse yaml.safe_load
        import re
        error_code_match = re.search(r'errors:\s*\n.*?code:\s*(\d+)', output, re.DOTALL)
        if error_code_match:
            error_code = int(error_code_match.group(1))
            if error_code != 0:
                return True
        
        # Text pattern fallback: check for common failure indicators
        # "transfer: False" in YAML-like output
        output_lower = output.lower().strip()
        if 'transfer: false' in output_lower or '"transfer":"false"' in output_lower:
            return True
        
        # Plain-text error patterns from cellframe-node-cli
        # The CLI often returns exit 0 with a human-readable error message
        _PLAIN_ERROR_PATTERNS = [
            'already exists',
            'not found',
            'can\'t find',
            'requires parameter',
            'requires one of parameters',
            'requres ',  # typo in cellframe-node (e.g. "token_emit command requres at least one valid certificate")
            'invalid parameter',
            'is invalid',
            'can\'t recognize command',
            'no such',
            'unknown command',
            'error:',
            'failed to',
            'can not ',
            'cannot ',
            'not enough',
            'insufficient',
        ]
        for pattern in _PLAIN_ERROR_PATTERNS:
            if pattern in output_lower:
                return True
        
        return False
    
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
                # self._log_to_file(f"[DEBUG] Applying CLI defaults: {defaults.cli}") # _log_to_file not available
                pass
            
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
        
        # Execute command with retry support for save_node operations
        # Use executor's _run_cli_command which has retry logic
        has_executor_ref = hasattr(self, '_executor_ref')
        has_run_cli = hasattr(self._executor_ref, '_run_cli_command') if has_executor_ref else False
        
        timeout = resolve_timeout(step.timeout, ctx, default=30)
        try:
            if has_executor_ref and has_run_cli:
                result = await self._executor_ref._run_cli_command(
                    command=cmd,
                    node=node,
                    timeout=timeout,
                    retry_on_init_failure=(step.save_node is not None)
                )
            else:
                result = await self.container_manager.exec_cli_command(
                    command=cmd,
                    node=node,
                    timeout=timeout
                )
        except asyncio.TimeoutError:
            raise ScenarioExecutionError(
                f"CLI step timed out after {timeout}s",
                step=cmd[:200],
                context={"timeout": timeout, "node": node}
            )
        
        output = result["stdout"]
        exit_code = result["returncode"]
        has_output_error = False
        
        # Check expectation FIRST - if command failed, don't try to extract data
        if step.expect == "success" and exit_code != 0:
            raise ScenarioExecutionError(
                f"CLI command failed: Expected success but got exit code {exit_code}",
                step=cmd[:100],
                context=result
            )
        elif step.expect == "error":
            # cellframe-node-cli always returns exit code 0 for successfully communicated
            # commands, even if the command handler returned an error code.
            # We must also check the output content for error indicators.
            has_output_error = self._detect_cli_error(output) if exit_code == 0 else True
            if exit_code == 0 and not has_output_error:
                raise ScenarioExecutionError(
                    f"CLI command succeeded: Expected error but got exit code 0 "
                    f"and no error indicators in output",
                    step=cmd[:100],
                    context={"output": output[:500]}
                )
        
        # Determine if command actually failed
        # For expect: error - check both exit code and output errors
        # For expect: success (default) - only exit code matters
        command_failed = exit_code != 0 or (step.expect == "error" and has_output_error)
        
        # Only extract data if command succeeded
        # If command failed but we're not checking expectation, skip extraction
        if command_failed:
            # Command failed - don't try to extract data from failed output
            if step.save_node or step.save_hash or step.save_wallet or step.save_token:
                raise ScenarioExecutionError(
                    f"Cannot extract data from failed command (exit_code={exit_code}). "
                    f"Command output may be empty or invalid.",
                    step=cmd[:100],
                    context={"exit_code": exit_code, "stderr": result.get("stderr", "")[:500]}
                )
            if step.save or step.save_to or step.save_map:
                variable_name = ctx.substitute(step.save or step.save_to) if (step.save or step.save_to) else None
                ctx.save_output(result.get("stderr", "") or "", variable_name, step.save_regex, step.save_map)
            return result
        
        # Extract and save values if requested (only if command succeeded)
        from ..extractors import DataExtractor
        from ..schema import ExtractType
        
        if step.save_node:
            variable_name = ctx.substitute(step.save_node)
            pattern = DataExtractor.get_default_pattern(ExtractType.NODE_ADDRESS)
            # Log output for debugging node address extraction issues
            logger.info("cli_save_node_output_debug", 
                       command=cmd[:100],
                       output_length=len(output),
                       output_preview=output[:500] if output else "EMPTY",
                       pattern=pattern)
            node_addr, error = DataExtractor.extract_and_validate(
                output, pattern, ExtractType.NODE_ADDRESS, required=True
            )
            if node_addr:
                ctx.set_variable(variable_name, node_addr)
                logger.debug("cli_step_saved_node", variable=variable_name, value=node_addr)
            else:
                raise ScenarioExecutionError(
                    f"Failed to extract node address from output: {error}",
                    step=cmd[:100],
                    context={"output": output[:500]}
                )
        
        if step.save_hash:
            variable_name = ctx.substitute(step.save_hash)
            
            # Check if output contains error in YAML format
            # CLI может возвращать ошибки в формате:
            # errors:
            #   code: 32
            #   message: ...
            try:
                import yaml
                output_data = yaml.safe_load(output)
                if isinstance(output_data, dict) and 'errors' in output_data:
                    error_info = output_data['errors']
                    error_code = error_info.get('code', -1)
                    error_message = error_info.get('message', '')
                    
                    if error_code != 0:
                        logger.error("cli_command_returned_error",
                                   variable=variable_name,
                                   error_code=error_code,
                                   error_message=error_message,
                                   command=cmd[:200])
                        raise ScenarioExecutionError(
                            f"CLI command returned error (code {error_code}): {error_message}",
                            step=cmd[:100],
                            context={
                                "error_code": error_code,
                                "error_message": error_message,
                                "output": output[:1000]
                            }
                        )
            except yaml.YAMLError:
                # Not YAML format - continue with hash extraction
                pass
            
            # CLI returned success (exit 0) but output may indicate node-side failure (e.g. tx_create)
            if output and ("Can't place TX datum in mempool" in output or
                          ("emission: False" in output and "message:" in output)):
                raise ScenarioExecutionError(
                    "CLI command reported failure in output (node could not process request). "
                    "Check node logs for details.",
                    step=cmd[:100],
                    context={"output": output[:500]}
                )
            
            # Extract hash from output
            pattern = DataExtractor.get_default_pattern(ExtractType.HASH)
            try:
                hash_value, error = DataExtractor.extract_and_validate(
                    output, pattern, ExtractType.HASH, required=True
                )
                if hash_value:
                    ctx.set_variable(variable_name, hash_value)
                    logger.debug("cli_step_saved_hash", variable=variable_name, value=hash_value)
            except Exception as e:
                # Log full output for debugging hash extraction failures
                logger.error("hash_extraction_failed",
                          variable=variable_name,
                          error=str(e),
                          output_preview=output[:1000],
                          command=cmd[:200])
                raise ScenarioExecutionError(
                    f"Failed to extract hash from output: {str(e)}",
                    step=cmd[:100],
                    context={"output": output[:1000], "pattern": pattern}
                )
        
        if step.save_wallet:
            variable_name = ctx.substitute(step.save_wallet)
            pattern = DataExtractor.get_default_pattern(ExtractType.WALLET_ADDRESS)
            wallet_addr, error = DataExtractor.extract_and_validate(
                output, pattern, ExtractType.WALLET_ADDRESS, required=True
            )
            if wallet_addr:
                ctx.set_variable(variable_name, wallet_addr)
                logger.debug("cli_step_saved_wallet", variable=variable_name, value=wallet_addr)
            else:
                raise ScenarioExecutionError(
                    f"Failed to extract wallet address from output: {error}",
                    step=cmd[:100],
                    context={"output": output[:500]}
                )
        
        if step.save_token:
            variable_name = ctx.substitute(step.save_token)
            pattern = DataExtractor.get_default_pattern(ExtractType.TOKEN_NAME)
            token_ticker, error = DataExtractor.extract_and_validate(
                output, pattern, ExtractType.TOKEN_NAME, required=True
            )
            if token_ticker:
                ctx.set_variable(variable_name, token_ticker)
                logger.debug("cli_step_saved_token", variable=variable_name, value=token_ticker)
            else:
                raise ScenarioExecutionError(
                    f"Failed to extract token ticker from output: {error}",
                    step=cmd[:100],
                    context={"output": output[:500]}
                )
        
        if step.save or step.save_to or step.save_map:
            variable_name = ctx.substitute(step.save or step.save_to) if (step.save or step.save_to) else None
            ctx.save_output(output, variable_name, step.save_regex, step.save_map)
        
        # Check contains/not_contains assertions (case-insensitive)
        # Supports both literal substring match and regex patterns
        import re
        output_lower = output.lower()
        
        if step.contains:
            expected_text = ctx.substitute(step.contains)
            expected_lower = expected_text.lower()
            if expected_lower not in output_lower:
                try:
                    if not re.search(expected_lower, output_lower):
                        raise ScenarioExecutionError(
                            f"Output does not contain expected text: '{expected_text}'",
                            step=cmd[:100],
                            context={"output": output[:500], "expected": expected_text}
                        )
                except re.error:
                    raise ScenarioExecutionError(
                        f"Output does not contain expected text: '{expected_text}'",
                        step=cmd[:100],
                        context={"output": output[:500], "expected": expected_text}
                    )
            logger.debug("cli_step_contains_passed", expected=expected_text)
        
        if step.not_contains:
            unexpected_text = ctx.substitute(step.not_contains)
            unexpected_lower = unexpected_text.lower()
            matched = unexpected_lower in output_lower
            if not matched:
                try:
                    matched = bool(re.search(unexpected_lower, output_lower))
                except re.error:
                    pass
            if matched:
                raise ScenarioExecutionError(
                    f"Output contains unexpected text: '{unexpected_text}'",
                    step=cmd[:100],
                    context={"output": output[:500], "unexpected": unexpected_text}
                )
            logger.debug("cli_step_not_contains_passed", unexpected=unexpected_text)
        
        # Record success result
        ctx.add_result("CLI", True, {
            "command": cmd,
            "node": node,
            "exit_code": exit_code
        })
        
        return result

