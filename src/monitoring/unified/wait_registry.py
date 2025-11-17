"""
Centralized waiter registry for YAML scenarios.

Provides single point of access to all waiters with unified API.
"""

from typing import Dict, Any, Callable, Optional, List
from ..utils.logger import get_logger

logger = get_logger(__name__)


class WaitRegistry:
    """
    Central registry for all waiters.
    
    Provides YAML-friendly interface to access waiters by name.
    """
    
    _registry: Dict[str, Any] = {}
    
    @classmethod
    def register(cls, name: str, waiter_class_or_func: Any):
        """
        Register a waiter in the registry.
        
        Args:
            name: Waiter name (e.g., "network_online")
            waiter_class_or_func: Waiter class or function
        """
        cls._registry[name] = waiter_class_or_func
        logger.debug(f"Registered waiter: {name}")
    
    @classmethod
    def get(cls, name: str) -> Any:
        """
        Get waiter by name.
        
        Args:
            name: Waiter name
            
        Returns:
            Waiter class or function
            
        Raises:
            KeyError: If waiter not found
        """
        if name not in cls._registry:
            raise KeyError(f"Waiter '{name}' not found in registry. Available: {list(cls._registry.keys())}")
        return cls._registry[name]
    
    @classmethod
    def list_all(cls) -> List[str]:
        """List all registered waiter names."""
        return list(cls._registry.keys())


# Initialize registry with all available waiters
def _initialize_registry():
    """Initialize waiter registry with all available waiters."""
    
    # Network waiters
    from ..waiters import (
        NetworkOnlineWaiter,
        NetworkSyncCompletionWaiter,
    )
    
    # Consensus waiters
    from ..waiter.dag_waiters import DAGEventWaiter
    from ..waiter.esbocs_waiters import ESBocsActiveWaiter
    from ..waiter.sync_waiters import FirstBlockWaiter
    
    # Ledger waiters
    from ..waiters import (
        LedgerTransactionWaiter,
        UTXOIndexationWaiter,
    )
    
    # Chain waiters
    from ..waiter.chain_waiters import (
        ChainDataPropagationWaiter,
        NetworkSyncWaiter,
    )
    
    # Token waiters
    from ..waiter.token_waiters import TokenInMempoolWaiter
    
    # Emission waiters
    from ..waiter.emission_waiters import EmissionSyncedInLedgerWaiter
    
    # Genesis waiters
    from ..waiter.genesis_waiters import (
        MasterContainersRunningWaiter,
        EmissionInLedgerWaiter,
        TransactionProcessedWaiter,
        GDBSyncCompleteWaiter,
        DelegationsSyncedWaiter,
        CLIReadyWaiter,
    )
    
    # Validator waiters
    from ..waiter.validator_waiters import (
        ValidatorModeActiveWaiter,
        StakeServiceReadyWaiter,
        ESBocsConsensusActiveWaiter,
    )
    
    # Registration waiters
    from ..waiter.registration_waiters import NodeListPropagationWaiter
    
    # GDB waiters
    from ..waiter.gdb_waiters import GDBClustersReadyWaiter
    
    # Network consensus monitor (special case - has wait_for_links_established method)
    from ..network_consensus import NetworkConsensusMonitor
    
    # Register all waiters
    WaitRegistry.register("network_online", NetworkOnlineWaiter)
    WaitRegistry.register("sync_complete", NetworkSyncCompletionWaiter)
    WaitRegistry.register("dag_event", DAGEventWaiter)
    WaitRegistry.register("esbocs_active", ESBocsActiveWaiter)
    WaitRegistry.register("first_block", FirstBlockWaiter)
    WaitRegistry.register("ledger_tx", LedgerTransactionWaiter)
    WaitRegistry.register("utxo_indexed", UTXOIndexationWaiter)
    WaitRegistry.register("chain_data_propagation", ChainDataPropagationWaiter)
    WaitRegistry.register("network_sync", NetworkSyncWaiter)
    WaitRegistry.register("token_in_mempool", TokenInMempoolWaiter)
    WaitRegistry.register("emission_synced", EmissionSyncedInLedgerWaiter)
    WaitRegistry.register("master_containers_running", MasterContainersRunningWaiter)
    WaitRegistry.register("emission_in_ledger", EmissionInLedgerWaiter)
    WaitRegistry.register("transaction_processed", TransactionProcessedWaiter)
    WaitRegistry.register("gdb_sync_complete", GDBSyncCompleteWaiter)
    WaitRegistry.register("delegations_synced", DelegationsSyncedWaiter)
    WaitRegistry.register("cli_ready", CLIReadyWaiter)
    WaitRegistry.register("validator_mode_active", ValidatorModeActiveWaiter)
    WaitRegistry.register("stake_service_ready", StakeServiceReadyWaiter)
    WaitRegistry.register("esbocs_consensus_active", ESBocsConsensusActiveWaiter)
    WaitRegistry.register("node_list_propagation", NodeListPropagationWaiter)
    WaitRegistry.register("gdb_clusters_ready", GDBClustersReadyWaiter)
    
    # Note: NetworkConsensusMonitor.wait_for_links_established is an instance method
    # It's handled directly in executor._execute_network_wait_step
    # We don't register it here as it requires a monitor instance


# Initialize registry on import
_initialize_registry()

# Export registry for direct access
WAITER_REGISTRY = WaitRegistry._registry

