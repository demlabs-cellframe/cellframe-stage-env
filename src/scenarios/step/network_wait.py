"""
Network wait step executor.
"""

from ...utils.logger import get_logger
from ...monitoring import MonitoringManager
from .base import StepExecutor
from ..schema import NetworkWaitStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class NetworkWaitStepExecutor(StepExecutor):
    """Executor for network wait steps."""
    
    def __init__(
        self,
        container_manager,
        log_file=None,
        debug: bool = False,
        node_cli_path: str = "cellframe-node-cli",
        resolve_node_alias_callback=None,
        get_node_config_callback=None
    ):
        """Initialize network wait executor."""
        super().__init__(container_manager, log_file, debug)
        self.node_cli_path = node_cli_path
        self.resolve_node_alias_callback = resolve_node_alias_callback
        self.get_node_config_callback = get_node_config_callback
    
    async def execute(self, step: NetworkWaitStep, ctx: RuntimeContext) -> None:
        """Execute network wait step."""
        logger.info(f"Waiting for network state: {step.wait_network} on nodes {step.nodes}")
        
        # Get monitoring manager singleton
        monitoring = MonitoringManager.get_instance(
            node_cli_path=self.node_cli_path,
            log_file=self.log_file
        )
        
        # Resolve node aliases
        if not self.resolve_node_alias_callback:
            raise RuntimeError("resolve_node_alias_callback not set for NetworkWaitStepExecutor")
        
        resolved_nodes = [self.resolve_node_alias_callback(node) for node in step.nodes]
        
        # Substitute variables
        network_name = ctx.substitute(step.network)
        wait_state = ctx.substitute(step.wait_network)
        
        try:
            if wait_state == "online":
                # Use NodeStateManager.wait_for_nodes_online for multiple nodes
                from ...network.node_states import NodeStateManager
                state_manager = NodeStateManager(
                    docker_client=self.container_manager.docker_client,
                    project_name="cellframe-stage",
                    cli_path=self.node_cli_path,
                    network_name=network_name
                )
                # Convert node IDs to NodeConfig objects
                if not self.get_node_config_callback:
                    raise RuntimeError("get_node_config_callback not set for NetworkWaitStepExecutor")
                node_configs = [self.get_node_config_callback(node_id) for node_id in resolved_nodes]
                await state_manager.wait_for_nodes_online(node_configs, timeout=step.timeout)
                
            elif wait_state == "offline":
                # Use NodeStateManager.wait_for_nodes_offline for multiple nodes
                from ...network.node_states import NodeStateManager
                state_manager = NodeStateManager(
                    docker_client=self.container_manager.docker_client,
                    project_name="cellframe-stage",
                    cli_path=self.node_cli_path,
                    network_name=network_name
                )
                # Convert node IDs to NodeConfig objects
                if not self.get_node_config_callback:
                    raise RuntimeError("get_node_config_callback not set for NetworkWaitStepExecutor")
                node_configs = [self.get_node_config_callback(node_id) for node_id in resolved_nodes]
                await state_manager.wait_for_nodes_offline(node_configs, timeout=step.timeout)
                
            elif wait_state == "links_connecting":
                # Use NetworkConsensusMonitor.wait_for_links_connecting_state
                from ...monitoring.network_consensus import NetworkConsensusMonitor
                nodes_dict = {node_id: None for node_id in resolved_nodes}
                monitor = NetworkConsensusMonitor(
                    nodes=nodes_dict,
                    node_cli_path=self.node_cli_path,
                    network_name=network_name
                )
                await monitor.wait_for_links_connecting_state(timeout=float(step.timeout))
                
            elif wait_state == "links_established":
                # Use NetworkConsensusMonitor
                from ...monitoring.network_consensus import NetworkConsensusMonitor
                nodes_dict = {node_id: None for node_id in resolved_nodes}
                monitor = NetworkConsensusMonitor(
                    nodes=nodes_dict,
                    node_cli_path=self.node_cli_path,
                    network_name=network_name
                )
                await monitor.wait_for_links_established(timeout=float(step.timeout))
                
            elif wait_state == "sync_complete":
                # Use NetworkSyncCompletionWaiter
                from ...monitoring.waiters import NetworkSyncCompletionWaiter
                waiter = NetworkSyncCompletionWaiter(
                    node_cli_path=self.node_cli_path,
                    network=network_name
                )
                await waiter.wait_for_sync_complete(resolved_nodes, timeout=step.timeout)
            else:
                raise ScenarioExecutionError(
                    f"Unknown network wait state: {wait_state}",
                    step=step
                )
            
            logger.info(f"✅ Network state '{wait_state}' achieved")
            ctx.add_result("network_wait", True, {"state": wait_state, "nodes": resolved_nodes})
            
        except Exception as e:
            error_msg = f"Network wait failed: {str(e)}"
            logger.error(error_msg)
            ctx.add_result("network_wait", False, {"state": wait_state, "error": str(e)})
            raise ScenarioExecutionError(error_msg, step=step)

