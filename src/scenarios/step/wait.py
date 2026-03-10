"""
Wait step executor.

Thin dispatcher layer that delegates to monitoring/dispatcher.py for all waiter logic.
"""

import asyncio
import re
import traceback

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import WaitStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class WaitStepExecutor(StepExecutor):
    """
    Executor for wait steps - supports both duration and waiter types.
    
    This is a thin dispatcher layer. All waiter logic is in monitoring/dispatcher.py.
    """
    
    def _expand_nodes_list(self, nodes, ctx) -> list:
        """Expand nodes that can be a template string or list."""
        if isinstance(nodes, str):
            # Template string like "{{all_nodes}}" - substitute and parse
            expanded = ctx.substitute(nodes)
            if expanded.startswith('[') and expanded.endswith(']'):
                import ast
                try:
                    return ast.literal_eval(expanded)
                except (ValueError, SyntaxError):
                    return [expanded]
            else:
                return [s.strip() for s in expanded.split(',') if s.strip()]
        return list(nodes)
    
    def __init__(
        self,
        container_manager,
        log_file=None,
        debug: bool = False,
        node_cli_path: str = "cellframe-node-cli",
        resolve_node_alias_callback=None,
        get_node_config_callback=None,
        create_exec_cli_callback=None
    ):
        """
        Initialize wait executor.
        
        Args:
            container_manager: Docker container manager
            log_file: Optional log file
            debug: Debug mode
            node_cli_path: Path to node CLI binary
            resolve_node_alias_callback: Callback to resolve node aliases
            get_node_config_callback: Callback to get node config
            create_exec_cli_callback: Callback to create exec_cli function for waiters
        """
        super().__init__(container_manager, log_file, debug)
        self.node_cli_path = node_cli_path
        self.resolve_node_alias_callback = resolve_node_alias_callback
        self.get_node_config_callback = get_node_config_callback
        self.create_exec_cli_callback = create_exec_cli_callback
        
        # Lazy-initialized dispatcher
        self._dispatcher = None
    
    def _get_dispatcher(self):
        """Get or create waiter dispatcher."""
        if self._dispatcher is None:
            from ...monitoring.dispatcher import WaiterDispatcher
            self._dispatcher = WaiterDispatcher(
                exec_cli_callback=self.create_exec_cli_callback,
                get_node_config_callback=self._wrap_get_node_config,
                docker_client=self.container_manager.docker_client if self.container_manager else None,
                node_cli_path=self.node_cli_path,
                log_file=self.log_file
            )
        return self._dispatcher
    
    def _wrap_get_node_config(self, node_name: str):
        """Wrap get_node_config to resolve aliases first."""
        if self.resolve_node_alias_callback:
            resolved = self.resolve_node_alias_callback(node_name)
            if self.get_node_config_callback:
                return self.get_node_config_callback(resolved)
        if self.get_node_config_callback:
            return self.get_node_config_callback(node_name)
        return None
    
    async def execute(self, step: WaitStep, ctx: RuntimeContext) -> None:
        """Execute wait step."""
        try:
            wait_value = ctx.substitute(step.wait) if step.wait else None
            
            # Check if wait value is a duration (e.g., '5s')
            is_duration = wait_value and re.match(r'^\d+(s|ms|m)$', wait_value)
            
            if is_duration:
                await self._execute_duration(step, ctx)
            elif wait_value or (hasattr(step, 'type') and step.type):
                await self._execute_waiter(step, ctx)
            else:
                raise ScenarioExecutionError("WaitStep requires 'wait' (duration or condition)", step=step)
        except Exception as e:
            logger.error(f"WaitStep execution failed. Step: {step}. Error: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    async def _execute_duration(self, step: WaitStep, ctx: RuntimeContext) -> None:
        """
        Execute duration-based wait with intelligent polling.
        
        For long waits (>30s), uses polling mechanism instead of blind sleep:
        - Polls every 5 seconds
        - Checks if conditions might be met early
        - Logs progress
        """
        duration_str = ctx.substitute(step.wait)
        
        match = re.match(r'(\d+)(s|ms|m)', duration_str)
        if not match:
            raise ScenarioExecutionError(f"Invalid duration format: {duration_str}")
        
        value = int(match.group(1))
        unit = match.group(2)
        
        if unit == 's':
            seconds = value
        elif unit == 'ms':
            seconds = value / 1000.0
        elif unit == 'm':
            seconds = value * 60
        else:
            raise ScenarioExecutionError(f"Unknown duration unit: {unit}")
        
        # For short durations (< 30s), just sleep
        if seconds < 30:
            logger.info(f"Waiting {duration_str} ({seconds}s)")
            await asyncio.sleep(seconds)
            return
        
        # For long durations, use intelligent polling
        logger.info(f"Waiting {duration_str} ({seconds}s) with polling every 5s")
        
        poll_interval = 5  # Poll every 5 seconds
        elapsed = 0
        
        while elapsed < seconds:
            # Sleep for poll interval or remaining time
            sleep_time = min(poll_interval, seconds - elapsed)
            await asyncio.sleep(sleep_time)
            elapsed += sleep_time
            
            # Log progress for long waits
            remaining = seconds - elapsed
            if remaining > 0:
                progress_pct = (elapsed / seconds) * 100
                logger.info(f"  ⏳ Progress: {progress_pct:.1f}% ({elapsed:.0f}s / {seconds:.0f}s) - {remaining:.0f}s remaining")
            
            # TODO: Could add early exit condition here if needed
            # For example, check if datum appeared, network synchronized, etc.
            # This would require access to waiter conditions and context
        
        logger.info(f"  ✅ Wait completed ({seconds}s elapsed)")
    
    async def _execute_waiter(self, step: WaitStep, ctx: RuntimeContext) -> None:
        """Execute waiter-based wait by dispatching to monitoring layer."""
        # Determine waiter type
        step_type = getattr(step, 'type', None)
        wait_type = ctx.substitute(step.wait) if step.wait else step_type
        
        if wait_type is None:
            raise ScenarioExecutionError(f"WaitStep 'wait' parameter is missing or None. Step: {step}", step=step)
        
        if not isinstance(wait_type, str):
            logger.error(f"wait_type is not a string! It is {type(wait_type)}: {wait_type}")
            wait_type = str(wait_type)

        logger.info(f"Waiting for condition: {wait_type}")
        
        # Handle polling waiters directly (cli, bash, python)
        if wait_type == "cli":
            await self._execute_cli_poll(step, ctx)
            return
        if wait_type == "bash":
            await self._execute_bash_poll(step, ctx)
            return
        if wait_type == "python":
            await self._execute_python_poll(step, ctx)
            return
        
        # Map clean names to internal waiter types
        WAITER_TYPE_MAPPING = {
            "mempool": "datum_in_mempool",
            "finalized": "datum_finalized",
            "network_online": "network_online",
            "global_db_sync": "global_db_sync",
            "cli_ready": "cli_ready",
            "block_created": "block_created",
        }
        
        registry_type = WAITER_TYPE_MAPPING.get(wait_type, wait_type)
        
        # Get dispatcher
        dispatcher = self._get_dispatcher()
        
        # Build params from step
        params = self._build_params(step, ctx)
        
        try:
            # Handle special waiters that have dedicated dispatcher methods
            if registry_type == "datum_in_mempool":
                result = await dispatcher.execute_datum_in_mempool(
                    datum_hash=params["datum_hash"],
                    node=params["node"],
                    network=params.get("network", ctx.variables.get('network_name', 'stagenet')),
                    chain=params.get("chain", "zerochain"),
                    timeout=float(step.timeout)
                )
            elif registry_type == "datum_finalized":
                result = await dispatcher.execute_datum_finalized(
                    datum_hash=params["datum_hash"],
                    node=params["node"],
                    network=params.get("network", ctx.variables.get('network_name', 'stagenet')),
                    chain=params.get("chain", "main"),
                    timeout=float(step.timeout),
                    check_master_nodes=step.check_master if hasattr(step, 'check_master') else True
                )
            else:
                # Generic waiter dispatch
                result = await dispatcher.execute_waiter(
                    waiter_type=registry_type,
                    params=params,
                    timeout=float(step.timeout)
                )
            
            logger.info(f"✅ Waiter '{wait_type}' completed")
            ctx.add_result("wait", True, {"type": wait_type, **result})
            
        except TimeoutError as e:
            # Check if waiter is optional (useful in retry loops)
            if getattr(step, 'optional', False):
                logger.warning(f"⚠️ Waiter '{wait_type}' timeout (optional, continuing): {str(e)}")
                ctx.add_result("wait", False, {"type": wait_type, "timeout": True, "error": str(e)})
                return  # Don't raise, just continue
            raise ScenarioExecutionError(
                f"Waiter '{wait_type}' timeout: {str(e)}",
                step=step,
                context=params
            )
        except RuntimeError as e:
            # Check if waiter is optional
            if getattr(step, 'optional', False):
                logger.warning(f"⚠️ Waiter '{wait_type}' failed (optional, continuing): {str(e)}")
                ctx.add_result("wait", False, {"type": wait_type, "error": str(e)})
                return
            raise ScenarioExecutionError(
                f"Waiter '{wait_type}' failed: {str(e)}",
                step=step,
                context=params
            )
    
    async def _execute_cli_poll(self, step, ctx) -> None:
        """
        Poll a CLI command until contains/not_contains condition is satisfied.

        Supports the same variable substitution and CLI-defaults mechanism as
        regular CLIStep (``-net``, ``-chain``, etc. are injected from the
        scenario's ``defaults.cli`` block via the global context).
        """
        if not step.cmd:
            raise ScenarioExecutionError(
                "wait: cli requires 'cmd' parameter", step=step
            )

        cmd = ctx.substitute(step.cmd)
        node_alias = ctx.substitute(step.node) if step.node else "node1"
        if self.resolve_node_alias_callback:
            node = self.resolve_node_alias_callback(node_alias)
        else:
            node = node_alias

        expected = ctx.substitute(step.contains) if step.contains else None
        unexpected = ctx.substitute(step.not_contains) if step.not_contains else None
        if not expected and not unexpected:
            raise ScenarioExecutionError(
                "wait: cli requires at least 'contains' or 'not_contains'",
                step=step,
            )

        # Apply CLI defaults from scenario context (e.g. -net, -chain)
        cli_defaults = ctx.variables.get("_cli_defaults")
        if cli_defaults and isinstance(cli_defaults, dict):
            from ...utils.cli_parser import get_cli_parser
            cli_parser = get_cli_parser()
            resolved = {k: ctx.substitute(v) for k, v in cli_defaults.items()}
            patched = cli_parser.apply_cli_defaults(cmd, resolved)
            if patched and isinstance(patched, str):
                cmd = patched

        timeout = float(step.timeout)
        interval = float(step.interval)
        elapsed = 0.0
        attempt = 0

        logger.info(
            f"  wait: cli cmd='{cmd}' node={node} "
            f"contains={expected!r} not_contains={unexpected!r} "
            f"timeout={timeout}s interval={interval}s"
        )

        import re as _re

        last_output = ""
        while elapsed < timeout:
            attempt += 1
            try:
                result = await self.container_manager.exec_cli_command(
                    command=cmd, node=node, timeout=30
                )
                output = result.get("stdout", "")
                last_output = output
                output_lower = output.lower()

                ok = True
                if expected:
                    exp_lower = expected.lower()
                    if exp_lower not in output_lower:
                        try:
                            if not _re.search(exp_lower, output_lower):
                                ok = False
                        except _re.error:
                            ok = False
                if unexpected:
                    unexp_lower = unexpected.lower()
                    found = unexp_lower in output_lower
                    if not found:
                        try:
                            found = bool(_re.search(unexp_lower, output_lower))
                        except _re.error:
                            pass
                    if found:
                        ok = False

                if ok:
                    logger.info(
                        f"  ✅ wait: cli satisfied after {attempt} attempts "
                        f"({elapsed:.0f}s)"
                    )
                    ctx.add_result("wait", True, {
                        "type": "cli", "attempts": attempt, "elapsed": elapsed
                    })
                    return

            except Exception as e:
                logger.debug(f"  wait: cli attempt {attempt} error: {e}")

            await asyncio.sleep(interval)
            elapsed += interval

        msg = (
            f"wait: cli timeout after {timeout}s ({attempt} attempts). "
            f"cmd='{cmd}' contains={expected!r} not_contains={unexpected!r}"
        )
        if getattr(step, "optional", False):
            logger.warning(f"⚠️ {msg} (optional, continuing)")
            ctx.add_result("wait", False, {"type": "cli", "timeout": True})
            return
        raise ScenarioExecutionError(
            msg, step=step,
            context={"last_output": last_output[:500]}
        )

    async def _execute_bash_poll(self, step, ctx) -> None:
        """
        Poll a bash script on a node until it exits with code 0.

        Optionally checks ``contains`` / ``not_contains`` on stdout.
        """
        if not step.script:
            raise ScenarioExecutionError(
                "wait: bash requires 'script' parameter", step=step
            )

        script = ctx.substitute(step.script)
        node_alias = ctx.substitute(step.node) if step.node else "node1"
        if self.resolve_node_alias_callback:
            node = self.resolve_node_alias_callback(node_alias)
        else:
            node = node_alias

        expected = ctx.substitute(step.contains) if step.contains else None
        unexpected = ctx.substitute(step.not_contains) if step.not_contains else None
        timeout = float(step.timeout)
        interval = float(step.interval)
        elapsed = 0.0
        attempt = 0

        logger.info(
            f"  wait: bash node={node} timeout={timeout}s interval={interval}s"
        )

        import re as _re
        last_output = ""

        while elapsed < timeout:
            attempt += 1
            try:
                result = await self.container_manager.exec_command(
                    command=["bash", "-c", script],
                    node=node,
                    timeout=30,
                )
                exit_code = result.get("returncode", -1)
                output = result.get("stdout", "")
                last_output = output

                if exit_code == 0:
                    ok = True
                    output_lower = output.lower()
                    if expected:
                        exp_lower = expected.lower()
                        if exp_lower not in output_lower:
                            try:
                                if not _re.search(exp_lower, output_lower):
                                    ok = False
                            except _re.error:
                                ok = False
                    if unexpected:
                        unexp_lower = unexpected.lower()
                        found = unexp_lower in output_lower
                        if not found:
                            try:
                                found = bool(_re.search(unexp_lower, output_lower))
                            except _re.error:
                                pass
                        if found:
                            ok = False

                    if ok:
                        logger.info(
                            f"  ✅ wait: bash satisfied after {attempt} attempts "
                            f"({elapsed:.0f}s)"
                        )
                        ctx.add_result("wait", True, {
                            "type": "bash", "attempts": attempt, "elapsed": elapsed
                        })
                        return

            except Exception as e:
                logger.debug(f"  wait: bash attempt {attempt} error: {e}")

            await asyncio.sleep(interval)
            elapsed += interval

        msg = (
            f"wait: bash timeout after {timeout}s ({attempt} attempts). "
            f"script='{script[:80]}'"
        )
        if getattr(step, "optional", False):
            logger.warning(f"⚠️ {msg} (optional, continuing)")
            ctx.add_result("wait", False, {"type": "bash", "timeout": True})
            return
        raise ScenarioExecutionError(
            msg, step=step,
            context={"last_output": last_output[:500]}
        )

    async def _execute_python_poll(self, step, ctx) -> None:
        """
        Poll a Python expression until it evaluates to a truthy value.

        The expression has access to ``ctx`` (RuntimeContext) and all
        scenario variables as local names.
        """
        if not step.script:
            raise ScenarioExecutionError(
                "wait: python requires 'script' parameter", step=step
            )

        expr = ctx.substitute(step.script)
        timeout = float(step.timeout)
        interval = float(step.interval)
        elapsed = 0.0
        attempt = 0

        logger.info(
            f"  wait: python expr='{expr[:80]}' timeout={timeout}s interval={interval}s"
        )

        while elapsed < timeout:
            attempt += 1
            try:
                local_vars = dict(ctx.variables)
                local_vars["ctx"] = ctx
                result = eval(expr, {"__builtins__": __builtins__}, local_vars)
                if result:
                    logger.info(
                        f"  ✅ wait: python satisfied after {attempt} attempts "
                        f"({elapsed:.0f}s), result={result!r}"
                    )
                    ctx.add_result("wait", True, {
                        "type": "python", "attempts": attempt,
                        "elapsed": elapsed, "result": str(result)
                    })
                    return
            except Exception as e:
                logger.debug(f"  wait: python attempt {attempt} error: {e}")

            await asyncio.sleep(interval)
            elapsed += interval

        msg = (
            f"wait: python timeout after {timeout}s ({attempt} attempts). "
            f"expr='{expr[:80]}'"
        )
        if getattr(step, "optional", False):
            logger.warning(f"⚠️ {msg} (optional, continuing)")
            ctx.add_result("wait", False, {"type": "python", "timeout": True})
            return
        raise ScenarioExecutionError(msg, step=step)

    def _build_params(self, step: WaitStep, ctx: RuntimeContext) -> dict:
        """
        Build parameters dict from step for dispatcher.
        
        Extracts and substitutes all relevant parameters from WaitStep.
        """
        params = {}
        
        # Datum hash
        if step.datum:
            params["datum_hash"] = ctx.substitute(step.datum)
        if hasattr(step, 'datum_hash') and step.datum_hash:
            params["datum_hash"] = ctx.substitute(step.datum_hash)
        if hasattr(step, 'emission_hash') and step.emission_hash:
            params["emission_hash"] = ctx.substitute(step.emission_hash)
        
        # Node(s)
        if step.node:
            node_alias = ctx.substitute(step.node)
            # Template might resolve to a list (e.g. {{_active_nodes}})
            if isinstance(node_alias, list):
                resolved_nodes = []
                for n in node_alias:
                    if self.resolve_node_alias_callback:
                        resolved_nodes.append(self.resolve_node_alias_callback(n))
                    else:
                        resolved_nodes.append(n)
                params["nodes"] = resolved_nodes
                if resolved_nodes:
                    params["node"] = resolved_nodes[0]
            else:
                if self.resolve_node_alias_callback:
                    resolved_node = self.resolve_node_alias_callback(node_alias)
                else:
                    resolved_node = node_alias
                params["node"] = resolved_node
                if not step.nodes:
                    params["nodes"] = [resolved_node]
        
        if step.nodes:
            # Expand nodes list (can be template string like "{{all_nodes}}")
            nodes_list = self._expand_nodes_list(step.nodes, ctx)
            resolved_nodes = []
            for n in nodes_list:
                node_alias = ctx.substitute(n)
                if self.resolve_node_alias_callback:
                    resolved_nodes.append(self.resolve_node_alias_callback(node_alias))
                else:
                    resolved_nodes.append(node_alias)
            params["nodes"] = resolved_nodes
            # Use first node as default "node" if not set
            if "node" not in params and resolved_nodes:
                params["node"] = resolved_nodes[0]
        
        # Network and chain
        params["network"] = ctx.substitute(step.network) if step.network else ctx.variables.get('network_name', 'stagenet')
        if step.chain:
            params["chain"] = ctx.substitute(step.chain)
        
        # Optional parameters
        if hasattr(step, 'expected_count') and step.expected_count is not None:
            params["expected_count"] = step.expected_count
        
        if hasattr(step, 'wallet') and step.wallet:
            params["wallet"] = ctx.substitute(step.wallet)
        
        if hasattr(step, 'token') and step.token:
            params["token"] = ctx.substitute(step.token)
        
        if hasattr(step, 'balance') and step.balance:
            params["balance"] = ctx.substitute(str(step.balance))
        elif hasattr(step, 'wait_for') and step.wait_for:
            params["balance"] = ctx.substitute(str(step.wait_for))
        
        # Block creation parameters
        if hasattr(step, 'min_blocks') and step.min_blocks is not None:
            params["min_blocks"] = step.min_blocks
        
        # GlobalDB group sync parameters
        if step.group:
            params["group"] = ctx.substitute(step.group)
        if step.key:
            params["key"] = ctx.substitute(step.key)
        
        return params
