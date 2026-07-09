"""
Waiter dispatcher for scenario execution.

Centralized waiter creation and execution logic.
WaitStepExecutor should delegate to this module for all waiter operations.

This module handles:
- Waiter class selection from registry
- Parameter defaults (poll_interval, timeouts)
- Waiter instantiation with proper dependencies
- Execution and result handling
- Automatic notify-server integration with polling fallback
"""

import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Dict, Any

from .unified.wait_registry import WaitRegistry
from .manager import MonitoringManager
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class WaiterConfig:
    """Configuration for waiter execution."""
    # Default poll intervals by waiter type
    POLL_INTERVALS = {
        "datum_in_mempool": 0.5,
        "datum_finalized": 2.0,
        "cli_ready": 1.0,
        "master_containers_running": 1.0,
        "delegations_synced": 2.0,
        "stake_service_ready": 2.0,
        "chipchain_consensus_active": 3.0,
        "first_block": 3.0,
        "wallet_balance": 2.0,
        "datum_in_chain": 2.0,
        "emission_in_ledger": 2.0,
        "global_db_sync": 2.0,
        "cli_ready": 0.5,
        "block_created": 3.0,
        "network_sync": 5.0,
        "chain_data_propagation": 5.0,
        "default": 2.0,
    }
    
    @classmethod
    def get_poll_interval(cls, waiter_type: str) -> float:
        """Get poll interval for waiter type."""
        return cls.POLL_INTERVALS.get(waiter_type, cls.POLL_INTERVALS["default"])


WAITER_NOTIFY_MAP: Dict[str, str] = {
    "network_online": "NetInfo",
    "sync_complete": "NetInfo",
    "wallet_balance": "WalletInfo",
    "datum_in_mempool": "MempoolEvent",
    "datum_in_chain": "ChainEvent",
    "block_created": "ChainEvent",
    "emission_in_ledger": "LedgerTxEvent",
    "transaction_processed": "MempoolEvent",
    "global_db_sync": "GDBEvent",
    "delegations_synced": "StakeEvent",
}
"""Maps waiter types to their notify-server ``class`` value.

Single-node waiters with definitive ``notify_matches()`` complete directly.
Multi-node waiters (``global_db_sync``, ``delegations_synced``) use
hint_only mode — a notification triggers ``check()`` across all nodes
rather than completing the waiter.
GDBEvent and StakeEvent are available in SDK >= 5.8; on 5.7 falls back
to polling."""

HINT_ONLY_WAITER_TYPES = {"global_db_sync", "delegations_synced", "block_created"}
"""Waiter types that use hint_only mode for notify (multi-node waiters)."""

NOTIFY_PORT = 8080


class WaiterDispatcher:
    """
    Centralized waiter dispatcher for scenario execution.
    
    Handles all waiter creation and execution, replacing the logic
    previously embedded in WaitStepExecutor.
    
    Usage:
        dispatcher = WaiterDispatcher(
            exec_cli_callback=lambda: exec_cli_func,
            get_node_config_callback=get_node_config,
            docker_client=docker_client,
            node_cli_path="cellframe-node-cli"
        )
        
        await dispatcher.execute(
            waiter_type="datum_finalized",
            params={"datum_hash": "0x...", "node": "node-1", "chain": "zerochain"},
            timeout=120
        )
    """
    
    def __init__(
        self,
        exec_cli_callback: Optional[Callable] = None,
        get_node_config_callback: Optional[Callable] = None,
        docker_client = None,
        node_cli_path: str = "cellframe-node-cli",
        log_file = None
    ):
        """
        Initialize waiter dispatcher.
        
        Args:
            exec_cli_callback: Factory that returns exec_cli function
            get_node_config_callback: Callback to get node config by name
            docker_client: Docker client for container operations
            node_cli_path: Path to CLI binary
            log_file: Log file path
        """
        self.exec_cli_callback = exec_cli_callback
        self.get_node_config_callback = get_node_config_callback
        self.docker_client = docker_client
        self.node_cli_path = node_cli_path
        self.log_file = log_file
    
    def _extract_node_id(self, node_name: str) -> int:
        """Extract node ID from node name.

        For non-standard service names (vpn-client-1, vpn-server-2, etc.)
        the numeric suffix does NOT correspond to the compose NODE_ID.
        We first try get_node_config_callback which knows the real mapping.
        """
        if self.get_node_config_callback:
            try:
                cfg = self.get_node_config_callback(node_name)
                if cfg and hasattr(cfg, 'node_id'):
                    return cfg.node_id
            except Exception:
                pass

        match = re.search(r'(?:node|root|master|full)-?(\d+)', node_name)
        if match:
            return int(match.group(1))
        match = re.search(r'(\d+)$', node_name)
        if match:
            return int(match.group(1))
        raise ValueError(f"Could not extract node ID from: {node_name}")
    
    def _get_exec_cli(self) -> Callable:
        """Get exec_cli function from callback."""
        if not self.exec_cli_callback:
            raise RuntimeError("exec_cli_callback not set")
        return self.exec_cli_callback()
    
    def _get_node_configs(self, nodes: List[str]) -> List:
        """Get node configs from callback."""
        if not self.get_node_config_callback:
            raise RuntimeError("get_node_config_callback not set")
        return [self.get_node_config_callback(n) for n in nodes]

    def _get_container_ip(self, node_id: int) -> Optional[str]:
        """Resolve container IP for notify server connection."""
        if not self.docker_client:
            return None
        container_name = f"cellframe-stage-node-{node_id}"
        try:
            container = self.docker_client.containers.get(container_name)
            networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
            return next(
                (net["IPAddress"] for net in networks.values()
                 if net.get("IPAddress")),
                None,
            )
        except Exception:
            return None

    def _try_enable_notify(self, waiter, waiter_type: str, node_id: int) -> None:
        """Enable notify on *waiter* if supported and reachable."""
        notify_class = WAITER_NOTIFY_MAP.get(waiter_type)
        if not notify_class:
            return
        if not hasattr(waiter, "notify_matches"):
            return
        ip = self._get_container_ip(node_id)
        if ip:
            hint_only = waiter_type in HINT_ONLY_WAITER_TYPES
            waiter.enable_notify(ip, notify_class, hint_only=hint_only)
            logger.debug("notify_enabled", waiter=waiter_type, ip=ip,
                         notify_class=notify_class, hint_only=hint_only)
    
    async def execute_datum_finalized(
        self,
        datum_hash: str,
        node: str,
        network: str = "stagenet",
        chain: str = "main",
        timeout: float = 120,
        check_master_nodes: bool = True
    ) -> Dict[str, Any]:
        """
        Wait for datum to be finalized.
        
        Uses MonitoringManager.datum which handles all timeout calculations internally.
        
        Args:
            datum_hash: Datum hash to monitor
            node: Node to check on
            network: Network name
            chain: Chain name
            timeout: Total timeout
            check_master_nodes: Whether to check master nodes
            
        Returns:
            Result dict with status and elapsed time
        """
        from ..scenarios.schema import DatumStatus
        
        monitoring = MonitoringManager.get_instance(
            node_cli_path=self.node_cli_path,
            log_file=self.log_file
        )
        
        # DatumMonitor.wait_for_datum() handles timeout defaults internally
        result = await monitoring.datum.wait_for_datum(
            datum_hash=datum_hash,
            node=node,
            network=network,
            chain=chain,
            check_master_nodes=check_master_nodes,
            timeout_total=timeout
        )
        
        if result.status != DatumStatus.SUCCESS:
            raise RuntimeError(
                f"Datum finalization failed: {result.error_message}",
            )
        
        return {
            "status": "success",
            "hash": datum_hash,
            "elapsed": result.elapsed_time,
            "details": result.details
        }
    
    async def execute_datum_in_mempool(
        self,
        datum_hash: str,
        node: str,
        network: str = "stagenet",
        chain: str = "zerochain",
        timeout: float = 60
    ) -> Dict[str, Any]:
        """
        Wait for datum to appear in mempool.
        
        Args:
            datum_hash: Datum hash to find
            node: Node to check on
            network: Network name
            chain: Chain name
            timeout: Timeout in seconds
            
        Returns:
            Result dict
        """
        from .waiter.datum_waiters import DatumInMempoolWaiter
        
        exec_cli = self._get_exec_cli()
        node_id = self._extract_node_id(node)
        poll_interval = WaiterConfig.get_poll_interval("datum_in_mempool")
        
        waiter = DatumInMempoolWaiter(
            exec_cli=exec_cli,
            node_id=node_id,
            datum_hash=datum_hash,
            network_name=network,
            chain=chain,
            poll_interval=poll_interval
        )

        self._try_enable_notify(waiter, "datum_in_mempool", node_id)
        await waiter.wait(timeout=timeout)
        
        return {"status": "success", "hash": datum_hash, "node": node}
    
    async def execute_waiter(
        self,
        waiter_type: str,
        params: Dict[str, Any],
        timeout: float
    ) -> Dict[str, Any]:
        """
        Execute waiter by type with given parameters.
        
        This is the main dispatch method that routes to appropriate waiter.
        
        Args:
            waiter_type: Type of waiter (e.g., "cli_ready", "delegations_synced")
            params: Parameters for the waiter (nodes, network, etc.)
            timeout: Timeout in seconds
            
        Returns:
            Result dict
        """
        # Get waiter class from registry
        try:
            waiter_class = WaitRegistry.get(waiter_type)
        except KeyError:
            raise ValueError(f"Unknown waiter type: {waiter_type}. "
                           f"Available: {WaitRegistry.list_all()}")
        
        # Get poll interval for this waiter type
        poll_interval = WaiterConfig.get_poll_interval(waiter_type)
        
        # Build waiter based on type
        waiter = self._build_waiter(waiter_type, waiter_class, params, poll_interval)

        if waiter_type in WAITER_NOTIFY_MAP:
            node_name = params.get("node")
            if not node_name:
                nodes_list = params.get("nodes", [])
                if nodes_list:
                    node_name = nodes_list[0]
            if node_name:
                try:
                    node_id = self._extract_node_id(node_name)
                    self._try_enable_notify(waiter, waiter_type, node_id)
                except Exception:
                    pass

        # Execute waiter
        await waiter.wait(timeout=timeout)
        
        return {
            "status": "success",
            "type": waiter_type,
            "params": params
        }
    
    def _build_waiter(
        self,
        waiter_type: str,
        waiter_class,
        params: Dict[str, Any],
        poll_interval: float
    ):
        """
        Build waiter instance with appropriate parameters.
        
        Args:
            waiter_type: Type of waiter
            waiter_class: Waiter class to instantiate
            params: Parameters from step
            poll_interval: Poll interval to use
            
        Returns:
            Waiter instance
        """
        exec_cli = None
        if self.exec_cli_callback:
            exec_cli = self._get_exec_cli()
        
        network = params.get("network", "stagenet")
        nodes = params.get("nodes", [])
        node = params.get("node")
        
        # Handle waiters that need node configs
        if waiter_type in ["delegations_synced", "stake_service_ready", "cli_ready", 
                          "gdb_sync_complete", "global_db_sync", "first_block", "chipchain_consensus_active",
                          "block_created", "network_sync", "chain_data_propagation"]:
            node_configs = self._get_node_configs(nodes)
            
            if waiter_type == "delegations_synced":
                return waiter_class(
                    exec_cli=exec_cli,
                    nodes=node_configs,
                    expected_count=params.get("expected_count", 0),
                    network_name=network,
                    poll_interval=poll_interval
                )
            elif waiter_type == "stake_service_ready":
                return waiter_class(
                    exec_cli=exec_cli,
                    nodes=node_configs,
                    network_name=network,
                    poll_interval=poll_interval
                )
            elif waiter_type == "cli_ready":
                return waiter_class(
                    exec_cli=exec_cli,
                    nodes=node_configs,
                    network_name=network,
                    poll_interval=poll_interval
                )
            elif waiter_type == "global_db_sync":
                if not node_configs:
                    raise ValueError(f"global_db_sync waiter requires at least one node")
                return waiter_class(
                    exec_cli=exec_cli,
                    nodes=node_configs,
                    network_name=network,
                    poll_interval=poll_interval,
                    group=params.get("group"),
                    key=params.get("key"),
                )
            elif waiter_type == "block_created":
                # BlockCreatedWaiter takes single node, chain, and min_blocks
                if not node_configs:
                    raise ValueError(f"block_created waiter requires at least one node")
                return waiter_class(
                    exec_cli=exec_cli,
                    node=node_configs[0],  # Use first node
                    chain=params.get("chain", "main"),
                    network_name=network,
                    min_blocks=params.get("min_blocks", 1),
                    poll_interval=poll_interval
                )
            elif waiter_type == "first_block":
                return waiter_class(
                    exec_cli=exec_cli,
                    network_name=network,
                    chain_name=params.get("chain", "main"),
                    master_nodes=node_configs,
                    poll_interval=poll_interval
                )
            elif waiter_type == "chipchain_consensus_active":
                # Create factory for stake_service_waiter
                def create_stake_waiter():
                    from .waiter.validator_waiters import StakeServiceReadyWaiter
                    return StakeServiceReadyWaiter(
                        exec_cli=exec_cli,
                        nodes=node_configs,
                        network_name=network,
                        poll_interval=poll_interval
                    )
                
                return waiter_class(
                    exec_cli=exec_cli,
                    nodes=node_configs,
                    network_name=network,
                    poll_interval=poll_interval,
                    stake_service_waiter_factory=create_stake_waiter
                )
            elif waiter_type == "network_sync":
                return waiter_class(
                    exec_cli=exec_cli,
                    docker_client=self.docker_client,
                    nodes=node_configs,
                    network_name=network,
                    poll_interval=poll_interval
                )
            elif waiter_type == "chain_data_propagation":
                return waiter_class(
                    exec_cli=exec_cli,
                    nodes=node_configs,
                    network_name=network,
                    chain_name=params.get("chain", "zerochain"),
                    poll_interval=poll_interval
                )
        
        # Handle waiters that need docker client
        if waiter_type == "master_containers_running":
            node_configs = self._get_node_configs(nodes)
            return waiter_class(
                docker_client=self.docker_client,
                master_nodes=node_configs,
                poll_interval=poll_interval
            )
        
        # Handle single-node waiters
        if waiter_type in ["wallet_balance", "datum_in_chain", "emission_in_ledger",
                           "transaction_processed"]:
            if not node:
                raise ValueError(f"node required for {waiter_type}")
            
            node_id = self._extract_node_id(node)
            
            if waiter_type == "wallet_balance":
                return waiter_class(
                    exec_cli=exec_cli,
                    node_id=node_id,
                    wallet_name=params.get("wallet", "fee_collector"),
                    token_ticker=params.get("token", "TCELL"),
                    expected_balance=params.get("balance"),
                    network_name=network,
                    poll_interval=poll_interval
                )
            elif waiter_type == "datum_in_chain":
                return waiter_class(
                    exec_cli=exec_cli,
                    node_id=node_id,
                    datum_hash=params.get("datum_hash") or params.get("datum"),
                    network_name=network,
                    chain=params.get("chain", "zerochain"),
                    poll_interval=poll_interval
                )
            elif waiter_type == "emission_in_ledger":
                return waiter_class(
                    exec_cli=exec_cli,
                    node_id=node_id,
                    emission_hash=params.get("emission_hash") or params.get("datum"),
                    network_name=network,
                    chain=params.get("chain", "zerochain"),
                    poll_interval=poll_interval
                )
            elif waiter_type == "transaction_processed":
                return waiter_class(
                    exec_cli=exec_cli,
                    node_id=node_id,
                    tx_hash=params.get("tx_hash") or params.get("hash"),
                    network_name=network,
                    chain=params.get("chain", "zerochain"),
                    poll_interval=poll_interval
                )
        
        # Generic fallback - pass common params
        raise ValueError(f"Waiter type {waiter_type} not yet supported in dispatcher")

