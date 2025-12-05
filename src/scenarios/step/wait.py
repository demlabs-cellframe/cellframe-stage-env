"""
Wait step executor.
"""

import asyncio
import re
import traceback

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import WaitStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


from ...monitoring.unified.wait_registry import WaitRegistry
from ...monitoring import MonitoringManager
from ..schema import DatumStatus

class WaitStepExecutor(StepExecutor):
    """Executor for wait steps - supports both duration and waiter types."""
    
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
    
    async def execute(self, step: WaitStep, ctx: RuntimeContext) -> None:
        """Execute wait step."""
        try:
            # Determine wait type
            # (WaitStep supports both duration and condition)
            wait_value = ctx.substitute(step.wait) if step.wait else None
            
            # Check if wait value is a duration (e.g., '5s')
            is_duration = wait_value and re.match(r'^\d+(s|ms|m)$', wait_value)
            
            if is_duration:
                await self._execute_duration(step, ctx)
            elif wait_value or (hasattr(step, 'type') and step.type):
                # It's a condition/waiter type
                await self._execute_waiter(step, ctx)
            else:
                raise ScenarioExecutionError("WaitStep requires 'wait' (duration or condition)", step=step)
        except Exception as e:
            logger.error(f"WaitStep execution failed. Step: {step}. Error: {str(e)}")
            logger.error(traceback.format_exc())
            raise

    async def _execute_duration(self, step: WaitStep, ctx: RuntimeContext) -> None:
        """Execute duration-based wait."""
        duration_str = ctx.substitute(step.wait)
        
        # Parse duration (e.g., '5s', '100ms', '2m')
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
        
        logger.info(f"Waiting {duration_str} ({seconds}s)")
        await asyncio.sleep(seconds)
    
    async def _execute_datum_mempool_waiter(self, step: WaitStep, ctx: RuntimeContext) -> None:
        """Execute datum_in_mempool waiter."""
        # Check required params
        # We can use 'datum' field or try to find it in other fields if needed
        datum_hash = ctx.substitute(step.datum) if step.datum else None
        if not datum_hash:
            raise ScenarioExecutionError("wait: mempool requires 'datum' parameter", step=step)
            
        # Check node
        nodes = step.nodes or ([step.node] if step.node else [])
        if not nodes:
            raise ScenarioExecutionError("wait: mempool requires 'node' or 'nodes' parameter", step=step)
            
        node_alias = ctx.substitute(nodes[0]) # Use first node
        resolved_node = self.resolve_node_alias_callback(node_alias)
        
        # Extract node ID from various formats: node-N, root-N, master-N, full-N
        import re
        match = re.search(r'(?:node|root|master|full)-(\d+)', resolved_node)
        if not match:
            raise ValueError(f"Could not extract node ID from resolved name: {resolved_node}")
        node_id = int(match.group(1))
        
        network = ctx.substitute(step.network) if step.network else ctx.get_variable('network_name')
        chain = ctx.substitute(step.chain) if step.chain else "zerochain"
        
        exec_cli_func = self.create_exec_cli_callback() if self.create_exec_cli_callback else None
        if not exec_cli_func:
            raise RuntimeError("create_exec_cli_callback not set for WaitStepExecutor")
            
        from ...monitoring.waiter.datum_waiters import DatumInMempoolWaiter
        
        waiter = DatumInMempoolWaiter(
            exec_cli=exec_cli_func,
            node_id=node_id,
            datum_hash=datum_hash,
            network_name=network,
            chain=chain,
            poll_interval=0.5
        )
        
        await waiter.wait(timeout=float(step.timeout))
        
        logger.info(f"✅ Datum {datum_hash} found in mempool")
        ctx.add_result("wait_in_mempool", True, {
            "hash": datum_hash,
            "node": node_alias
        })

    async def _execute_datum_finalized_waiter(self, step: WaitStep, ctx: RuntimeContext) -> None:
        """Execute datum_finalized waiter (wait for full processing)."""
        datum_hash = ctx.substitute(step.datum) if step.datum else None
        if not datum_hash:
            raise ScenarioExecutionError("wait: finalized requires 'datum' parameter", step=step)
            
        node = ctx.substitute(step.node) if step.node else "node1"
        network = ctx.substitute(step.network) if step.network else "stagenet"
        chain = ctx.substitute(step.chain) if step.chain else "main"
        
        logger.info(f"Waiting for datum {datum_hash[:16]}... to be finalized")
        
        # Get monitoring manager singleton
        monitoring = MonitoringManager.get_instance(
            node_cli_path=self.node_cli_path,
            log_file=self.log_file
        )
        
        # Monitor datum
        result = await monitoring.datum.wait_for_datum(
            datum_hash=datum_hash,
            node=node,
            network=network,
            chain=chain,
            check_master_nodes=step.check_master,
            timeout_total=step.timeout,
            # Use reasonable defaults relative to total timeout or fixed defaults
            timeout_mempool=max(60, int(step.timeout * 0.4)),
            timeout_verification=max(60, int(step.timeout * 0.4)),
            timeout_in_blocks=max(60, int(step.timeout * 0.4))
        )
        
        if result.status != DatumStatus.SUCCESS:
             error_msg = f"Datum finalization failed: {result.error_message}"
             logger.error(error_msg)
             raise ScenarioExecutionError(
                error_msg,
                step=step,
                context={
                    "datum_hash": datum_hash,
                    "status": result.status.value,
                    "elapsed_time": result.elapsed_time,
                    "details": result.details
                }
            )
            
        logger.info(f"✅ Datum {datum_hash[:16]}... finalized successfully in {result.elapsed_time:.1f}s")
        ctx.add_result("wait_finalized", True, {
            "hash": datum_hash,
            "elapsed": result.elapsed_time
        })

    async def _execute_waiter(self, step: WaitStep, ctx: RuntimeContext) -> None:
        """Execute waiter-based wait."""
        # Use getattr to safely access deprecated 'type' field if it exists in runtime object
        step_type = getattr(step, 'type', None)
        wait_type = ctx.substitute(step.wait) if step.wait else step_type
        
        if wait_type is None:
             raise ScenarioExecutionError(f"WaitStep 'wait' parameter is missing or None. Step: {step}", step=step)
             
        # Guard against recursive objects
        if not isinstance(wait_type, str):
            logger.error(f"wait_type is not a string! It is {type(wait_type)}: {wait_type}")
            wait_type = str(wait_type)

        logger.info(f"Waiting for condition: {wait_type}")
        
        # Map clean names to internal waiter types if needed
        WAITER_TYPE_MAPPING = {
            "mempool": "datum_in_mempool",
            "finalized": "datum_finalized",
            "network_online": "network_online",
        }
        
        registry_type = WAITER_TYPE_MAPPING.get(wait_type, wait_type)
        
        # Handle special waiters
        if registry_type == "datum_in_mempool":
            await self._execute_datum_mempool_waiter(step, ctx)
            return
        elif registry_type == "datum_finalized":
            await self._execute_datum_finalized_waiter(step, ctx)
            return

        # Get waiter class from registry
        waiter_class = None
        try:
            waiter_class = WaitRegistry.get(registry_type)
        except KeyError:
            pass
            
        if not waiter_class:
            raise ScenarioExecutionError(f"Unknown waiter type: {wait_type}")
        
        # Resolve nodes
        if not self.resolve_node_alias_callback:
            raise RuntimeError("resolve_node_alias_callback not set for WaitStepExecutor")
        
        nodes = [self.resolve_node_alias_callback(ctx.substitute(n)) for n in (step.nodes or [])]
        network_name = ctx.substitute(step.network) if step.network else ctx.get_variable('network_name')
        
        # Create waiter instance based on type
        if registry_type == "delegations_synced":
            if not step.nodes or step.expected_count is None:
                raise ScenarioExecutionError("nodes and expected_count required for delegations_synced", step=step)
            
            exec_cli_func = self.create_exec_cli_callback() if self.create_exec_cli_callback else None
            if not exec_cli_func:
                raise RuntimeError("create_exec_cli_callback not set for WaitStepExecutor")
            
            waiter = waiter_class(
                exec_cli=exec_cli_func,
                nodes=[self.get_node_config_callback(n) for n in nodes] if self.get_node_config_callback else [],
                expected_count=step.expected_count,
                network_name=network_name,
                poll_interval=2.0
            )
            await waiter.wait(timeout=float(step.timeout))
            
        elif registry_type == "stake_service_ready":
            if not step.nodes:
                raise ScenarioExecutionError("nodes required for stake_service_ready", step=step)
            
            exec_cli_func = self.create_exec_cli_callback() if self.create_exec_cli_callback else None
            if not exec_cli_func:
                raise RuntimeError("create_exec_cli_callback not set for WaitStepExecutor")
            
            waiter = waiter_class(
                exec_cli=exec_cli_func,
                nodes=[self.get_node_config_callback(n) for n in nodes] if self.get_node_config_callback else [],
                network_name=network_name,
                poll_interval=2.0
            )
            await waiter.wait(timeout=float(step.timeout))
            
        elif registry_type == "esbocs_consensus_active":
            if not step.nodes:
                raise ScenarioExecutionError("nodes required for esbocs_consensus_active", step=step)
            
            exec_cli_func = self.create_exec_cli_callback() if self.create_exec_cli_callback else None
            if not exec_cli_func:
                raise RuntimeError("create_exec_cli_callback not set for WaitStepExecutor")
            
            # Create factory for stake_service_waiter
            def create_stake_waiter():
                from ...monitoring.waiter.validator_waiters import StakeServiceReadyWaiter
                return StakeServiceReadyWaiter(
                    exec_cli=exec_cli_func,
                    nodes=[self.get_node_config_callback(n) for n in nodes] if self.get_node_config_callback else [],
                    network_name=network_name,
                    poll_interval=2.0
                )
            
            waiter = waiter_class(
                exec_cli=exec_cli_func,
                nodes=[self.get_node_config_callback(n) for n in nodes] if self.get_node_config_callback else [],
                network_name=network_name,
                poll_interval=3.0,
                stake_service_waiter_factory=create_stake_waiter
            )
            await waiter.wait(timeout=float(step.timeout))
            
        elif registry_type == "first_block":
            if not step.nodes or not step.chain:
                raise ScenarioExecutionError("nodes and chain required for first_block", step=step)
            
            exec_cli_func = self.create_exec_cli_callback() if self.create_exec_cli_callback else None
            if not exec_cli_func:
                raise RuntimeError("create_exec_cli_callback not set for WaitStepExecutor")
            
            waiter = waiter_class(
                exec_cli=exec_cli_func,
                network_name=network_name,
                chain_name=ctx.substitute(step.chain),
                master_nodes=[self.get_node_config_callback(n) for n in nodes] if self.get_node_config_callback else [],
                poll_interval=3.0
            )
            await waiter.wait(timeout=float(step.timeout))
            
        elif registry_type == "master_containers_running":
            if not step.nodes:
                raise ScenarioExecutionError(f"nodes required for {registry_type}", step=step)
            
            waiter = waiter_class(
                docker_client=self.container_manager.docker_client,
                master_nodes=[self.get_node_config_callback(n) for n in nodes] if self.get_node_config_callback else [],
                poll_interval=1.0
            )
            await waiter.wait(timeout=float(step.timeout))

        elif registry_type == "cli_ready":
            if not step.nodes:
                raise ScenarioExecutionError(f"nodes required for {registry_type}", step=step)
            
            exec_cli_func = self.create_exec_cli_callback() if self.create_exec_cli_callback else None
            if not exec_cli_func:
                raise RuntimeError("create_exec_cli_callback not set for WaitStepExecutor")
            
            waiter = waiter_class(
                exec_cli=exec_cli_func,
                nodes=[self.get_node_config_callback(n) for n in nodes] if self.get_node_config_callback else [],
                network_name=network_name,
                poll_interval=1.0
            )
            await waiter.wait(timeout=float(step.timeout))
        
        elif registry_type == "wallet_balance":
            # Get node (single node for wallet balance check)
            if not step.node:
                raise ScenarioExecutionError(f"node required for {registry_type}", step=step)
            
            node_alias = ctx.substitute(step.node)
            node_name = self.resolve_node_alias_callback(node_alias)
            
            # Extract node ID from node name (e.g., "node1" -> 1, "root-1" -> 1)
            import re
            match = re.search(r'(\d+)$', node_name)
            if not match:
                raise ScenarioExecutionError(f"Cannot extract node ID from: {node_name}", step=step)
            node_id = int(match.group(1))
            
            # Get wallet, token and balance parameters
            wallet_name = ctx.substitute(step.wallet) if hasattr(step, 'wallet') and step.wallet else "fee_collector"
            token_ticker = ctx.substitute(step.token) if hasattr(step, 'token') and step.token else "TCELL"
            
            # Get expected balance condition (optional)
            expected_balance = None
            if hasattr(step, 'balance') and step.balance:
                expected_balance = ctx.substitute(str(step.balance))
            elif hasattr(step, 'wait_for') and step.wait_for:
                expected_balance = ctx.substitute(str(step.wait_for))
            
            exec_cli_func = self.create_exec_cli_callback() if self.create_exec_cli_callback else None
            if not exec_cli_func:
                raise RuntimeError("create_exec_cli_callback not set for WaitStepExecutor")
            
            waiter = waiter_class(
                exec_cli=exec_cli_func,
                node_id=node_id,
                wallet_name=wallet_name,
                token_ticker=token_ticker,
                expected_balance=expected_balance,
                network_name=network_name,
                poll_interval=2.0
            )
            await waiter.wait(timeout=float(step.timeout))
            
        else:
            raise ScenarioExecutionError(f"Waiter type {wait_type} not yet implemented in executor", step=step)
        
        logger.info(f"✅ Waiter '{wait_type}' completed")
        ctx.add_result("wait", True, {"type": wait_type, "nodes": nodes})
