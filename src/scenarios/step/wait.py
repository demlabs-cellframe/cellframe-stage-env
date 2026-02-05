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
                    network=params.get("network", "stagenet"),
                    chain=params.get("chain", "zerochain"),
                    timeout=float(step.timeout)
                )
            elif registry_type == "datum_finalized":
                result = await dispatcher.execute_datum_finalized(
                    datum_hash=params["datum_hash"],
                    node=params["node"],
                    network=params.get("network", "stagenet"),
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
            raise ScenarioExecutionError(
                f"Waiter '{wait_type}' timeout: {str(e)}",
                step=step,
                context=params
            )
        except RuntimeError as e:
            raise ScenarioExecutionError(
                f"Waiter '{wait_type}' failed: {str(e)}",
                step=step,
                context=params
            )
    
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
            if self.resolve_node_alias_callback:
                resolved_node = self.resolve_node_alias_callback(node_alias)
            else:
                resolved_node = node_alias
            params["node"] = resolved_node
            # If no nodes list specified, create single-element list from node
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
        
        return params
