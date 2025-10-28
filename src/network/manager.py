"""
Network manager for cellframe test environment.

Manages the lifecycle of test network:
- Dynamic node creation based on topology
- Node startup/shutdown
- Network readiness checking
- Node discovery and configuration
- Snapshot-based suite isolation for fast environment restoration
"""

import asyncio
from pathlib import Path
from typing import Dict, List, Optional

from ..config.loader import ConfigLoader, NetworkTopology
from ..config.generator import ConfigGenerator
from ..docker.compose import DockerComposeManager
from ..monitoring.health import HealthChecker, HealthStatus
from ..utils.logger import get_logger
from ..utils.artifacts import ArtifactsManager
from ..snapshots.manager import SnapshotManager, SnapshotMode
from .models import NodeConfig
from .genesis import GenesisInitializer

logger = get_logger(__name__)


class NetworkManager:
    """Manage cellframe test network lifecycle."""
    
    def __init__(self, base_path: Path, topology_name: str = "default", config_path: Optional[Path] = None):
        """
        Initialize network manager.
        
        Args:
            base_path: Base path to stage-env directory
            topology_name: Name of topology to use
            config_path: Optional path to stage-env.cfg
        """
        self.base_path = base_path
        self.topology_name = topology_name
        self.config_path = config_path
        
        # CLI path for node commands
        self.node_cli_path = "cellframe-node-cli"
        
        # Load configuration
        self.config_loader = ConfigLoader(base_path, config_path)
        self.topology = self.config_loader.load_topology(topology_name)
        
        # Config generator
        self.config_generator = ConfigGenerator(base_path, config_path)
        
        # Docker compose manager
        self.compose = DockerComposeManager(
            base_path,
            project_name="cellframe-stage"
        )
        
        # Health checker
        self.health_checker = HealthChecker()
        
        # Genesis initializer
        self.genesis = GenesisInitializer(
            base_path,
            network_name=self.topology.network.name,
            config_path=config_path
        )
        
        # Node configurations
        self.nodes: Dict[str, NodeConfig] = {}
        
        # Load timeouts from config
        self.timeouts = self.config_loader.get_timeouts()
        
        # Load paths from config
        self.paths_config = self.config_loader.get_paths_config()
        
        # Initialize artifacts manager
        artifacts_config = self.config_loader.get_artifacts_config()
        self.artifacts_manager = ArtifactsManager(base_path, artifacts_config)
        
        # Initialize snapshot manager for suite isolation
        suite_isolation_config = self.config_loader.get_suite_isolation_config()
        snapshot_mode_str = suite_isolation_config.get('mode', 'filesystem')
        
        # Convert mode string to enum
        try:
            snapshot_mode = SnapshotMode(snapshot_mode_str)
        except ValueError:
            logger.warning("invalid_snapshot_mode",
                          mode=snapshot_mode_str,
                          fallback="filesystem")
            snapshot_mode = SnapshotMode.FILESYSTEM
        
        # Pass full config including cache_dir
        snapshot_config = dict(suite_isolation_config)
        snapshot_config['cache_dir'] = self.paths_config.get('cache_dir', '../testing/cache')
        
        self.snapshot_manager = SnapshotManager(
            base_path,
            mode=snapshot_mode,
            config=snapshot_config
        )
        
        self.suite_isolation_config = suite_isolation_config
        
        logger.info("network_manager_initialized",
                   topology=topology_name,
                   network=self.topology.network.name,
                   timeouts=self.timeouts,
                   cache_dir=self.paths_config.get('cache_dir'),
                   snapshot_mode=snapshot_mode.value)
    
    def generate_node_configs(self) -> List[NodeConfig]:
        """
        Generate node configurations from topology.
        
        Returns:
            List of NodeConfig objects
        """
        logger.info("generating_node_configs")
        
        configs = []
        node_counter = 1
        
        # Base settings from topology
        settings = self.topology.network_settings
        
        for node_type, node_spec in self.topology.topology.items():
            for i in range(node_spec.count):
                # Determine if seed node and balancer based on topology spec
                is_seed = getattr(node_spec, 'is_seed_node', node_spec.role == 'root')
                balancer_enabled = getattr(node_spec, 'balancer_enabled', node_spec.role == 'root')
                consensus_participation = getattr(node_spec, 'consensus_participation', False)
                
                config = NodeConfig(
                    node_id=node_counter,
                    role=node_spec.role,
                    node_type=node_type,
                    rpc_port=settings.base_rpc_port + node_counter - 1,
                    p2p_port=settings.base_p2p_port + node_counter - 1,
                    cf_port=settings.base_cf_port + node_counter - 1,
                    http_port=settings.base_http_port + node_counter - 1,
                    ip_address=self._calculate_ip(
                        settings.base_ip,
                        node_counter
                    ),
                    is_seed_node=is_seed,
                    balancer_enabled=balancer_enabled,
                    consensus_participation=consensus_participation
                )
                
                configs.append(config)
                self.nodes[f"node{node_counter}"] = config
                node_counter += 1
        
        logger.info("node_configs_generated",
                   count=len(configs),
                   seed_nodes=sum(1 for c in configs if c.is_seed_node),
                   validators=sum(1 for c in configs if c.consensus_participation))
        return configs
    
    def _calculate_ip(self, base_ip: str, node_id: int) -> str:
        """
        Calculate node IP address.
        
        Args:
            base_ip: Base IP (e.g., "172.20.0.10")
            node_id: Node ID
            
        Returns:
            IP address string
        """
        parts = base_ip.split(".")
        last_octet = int(parts[3]) + node_id - 1
        return f"{parts[0]}.{parts[1]}.{parts[2]}.{last_octet}"
    
    async def start(
        self,
        rebuild: bool = False,
        wait_ready: bool = True,
    ) -> None:
        """
        Start the test network.
        
        Args:
            rebuild: Rebuild Docker images before starting
            wait_ready: Wait for all nodes to be ready
        """
        logger.info("starting_network",
                   topology=self.topology_name,
                   rebuild=rebuild)
        
        # Stop previous environment FIRST (keep volumes - they contain certs!)
        logger.info("stopping_previous_environment")
        try:
            self.compose.down(volumes=False, remove_images=False)
            logger.info("previous_environment_stopped")
        except Exception as e:
            logger.debug("no_previous_environment", error=str(e))
        
        # Clean up any remaining stale resources
        self.compose.cleanup_stale_resources()
        
        # CRITICAL: Clean node data AFTER stopping old network, BEFORE any generation
        # This ensures clean slate before configs/certs generation
        if self.suite_isolation_config.get('auto_create_on_startup', True):
            if self.snapshot_manager.mode != SnapshotMode.DISABLED:
                logger.info("cleaning_node_data_after_stop")
                self._clean_node_data()
        
        # Generate node configurations
        if not self.nodes:
            node_configs = self.generate_node_configs()
        else:
            node_configs = list(self.nodes.values())
        
        # Generate configuration files and certificates
        logger.info("generating_configs_and_certs")
        self.config_generator.generate_all(
            self.topology,
            node_configs,
            force=rebuild
        )
        
        # Generate dynamic docker-compose.yml for all nodes
        logger.info("generating_docker_compose")
        cache_dir_relative = self.paths_config.get('cache_dir', 'cache')
        self.compose.generate_compose_for_nodes(node_configs, cache_dir_relative=cache_dir_relative)
        
        # Build images if requested
        if rebuild:
            logger.info("rebuilding_images")
            self.compose.build(no_cache=rebuild)
        
        # Separate nodes by role for phased startup
        root_nodes = [n for n in node_configs if n.role == 'root']
        master_nodes = [n for n in node_configs if n.role == 'master']
        full_nodes = [n for n in node_configs if n.role == 'full']
        
        root_node_ids = [n.node_id for n in root_nodes]
        master_node_ids = [n.node_id for n in master_nodes]
        full_node_ids = [n.node_id for n in full_nodes]
        
        logger.info("node_distribution", 
                   root=len(root_nodes), 
                   master=len(master_nodes), 
                   full=len(full_nodes))
        
        # =================================================================
        # PHASE 1: START ROOT NODES WITH SEED_MODE FOR DAG GENESIS
        # =================================================================
        logger.info("=== PHASE 1: ROOT Nodes Startup (DAG-PoA Genesis) ===")
        
        try:
            # ROOT nodes already have seed_mode=true in configs (set during config generation)
            # This allows creation of first DAG events without parent hashes
            
            # Start ONLY root nodes
            root_services = [f"node-{nid}" for nid in root_node_ids]
            logger.info("starting_root_nodes_only", services=root_services, seed_mode=True)
            self.compose.up(services=root_services, detach=True, wait=False)
            
            # Wait for root nodes to be fully initialized with intelligent monitoring
            logger.info("waiting_for_root_nodes_ready")
            from ..monitoring.network_consensus import NetworkConsensusMonitor
            
            # Create temporary nodes dict for root nodes only
            # IMPORTANT: keys must be "node1", "node2", "node3" (without dash!)
            root_nodes_dict = {f"node{n.node_id}": n for n in root_nodes}
            consensus_monitor = NetworkConsensusMonitor(
                nodes=root_nodes_dict,
                node_cli_path=self.node_cli_path
            )
            
            # Wait for ROOT nodes to reach NET_STATE_LINKS_CONNECTING
            # This means network subsystems are initialized and ready for node registration
            logger.info("waiting_for_network_ready_for_registration")
            await consensus_monitor.wait_for_links_connecting_state(timeout=60.0)
            logger.info("root_nodes_ready_for_registration")
            
            # Register ONLY ROOT nodes (first 3) in node1's node list immediately
            # This pre-populates the essential validators; other nodes will self-discover
            logger.info("pre_registering_root_nodes_in_node1")
            await self.genesis.registration_mgr.register_all_nodes_via_cli(root_nodes)
            logger.info("root_nodes_pre_registered_in_node1", count=len(root_nodes))
            
            # CRITICAL: SOFT reconnect to establish links for DAG-PoA consensus
            # Without links, DAG events cannot be created (consensus requires active validators)
            logger.info("soft_reconnect_for_dag_consensus")
            await self.genesis.registration_mgr.soft_network_reconnect(root_nodes, wait_for_links=True)
            logger.info("dag_consensus_links_established")
            
            # Generate fee wallet
            logger.info("generating_fee_wallet")
            fee_addr = await self.genesis.token_mgr.generate_fee_wallet()
            logger.info("fee_wallet_created", address=fee_addr)
            
            # Update fee_addr in main.cfg on ALL nodes
            logger.info("updating_fee_addr_in_all_configs")
            await self.genesis.config_mgr.update_fee_addr_in_config(fee_addr, node_configs)
            logger.info("fee_addr_updated_in_configs")
            
            # Create TCELL token on zerochain
            logger.info("creating_tcell_token_on_zerochain")
            token_hash = await self.genesis.token_mgr.create_native_token()
            logger.info("tcell_token_created", hash=token_hash[:16])
            
            # Process token_decl through DAG-PoA (with seed_mode!)
            logger.info("processing_token_decl_dag_poa")
            await self.genesis.sync_mgr.process_zerochain_datum(token_hash, root_nodes)
            logger.info("token_decl_finalized_in_dag")
            
            # Emit TCELL
            logger.info("emitting_tcell_tokens")
            emission_hash = await self.genesis.token_mgr.emit_native_token(fee_addr)
            logger.info("tcell_emission_created", hash=emission_hash[:16])
            
            # Process emission through DAG-PoA (with seed_mode!)
            logger.info("processing_emission_dag_poa")
            await self.genesis.sync_mgr.process_zerochain_datum(emission_hash, root_nodes)
            logger.info("emission_finalized_in_dag")
            
            # DIAGNOSTIC: Verify emission is visible on ROOT nodes BEFORE restart
            logger.info("verifying_emission_on_root_nodes", emission=emission_hash[:16])
            for root_node in root_nodes[:1]:  # Check first ROOT node
                exit_code, stdout, _ = self.genesis._exec_cli(
                    root_node.node_id,
                    f"ledger list -net {self.topology.network.name} -chain zerochain",
                    check_output=False
                )
                has_emission = emission_hash.lower() in stdout.lower() if stdout else False
                logger.info("root_emission_check",
                           node=f"node{root_node.node_id}",
                           has_emission=has_emission,
                           exit_code=exit_code,
                           ledger_preview=stdout[:300] if stdout else "empty")
            
            # CRITICAL: Get genesis EVENT hash from zerochain and update configs!
            logger.info("getting_zerochain_genesis_event_hash")
            zerochain_genesis_hash = await self.genesis.config_mgr.get_genesis_event_hash("zerochain")
            if not zerochain_genesis_hash:
                raise RuntimeError("Failed to retrieve zerochain genesis event hash")
            logger.info("zerochain_genesis_event_hash", hash=zerochain_genesis_hash[:16])
            
            # Update static_genesis_event_hash in zerochain.cfg for ALL nodes
            logger.info("updating_static_genesis_event_in_all_configs")
            await self.genesis.config_mgr.update_static_genesis_in_config("zerochain", zerochain_genesis_hash, node_configs)
            logger.info("zerochain_static_genesis_updated")
            
            # CRITICAL: HARD RESTART #1 - Apply DAG genesis event + disable seed_mode
            # Full container restart to reload configs from disk
            logger.info("=== HARD RESTART #1: After DAG Genesis Event ===")
            
            # Step 1: Disable seed_mode in ROOT configs (write to disk)
            logger.info("disabling_seed_mode_for_root_nodes")
            self.genesis.config_mgr.disable_seed_mode_in_configs(root_node_ids)
            
            # Step 2: Hard restart ROOT nodes with config reload
            from .node_lifecycle import NodeLifecycleManager
            lifecycle_mgr = NodeLifecycleManager(project_name=self.compose.project_name)
            
            logger.info("hard_restarting_root_nodes_for_config_reload")
            await lifecycle_mgr.hard_restart_with_config_reload(
                service_names=root_services,
                compose_manager=self.compose,
                flush_timeout=60
            )
            
            # Step 3: Wait for ROOT nodes to come back online and establish links
            logger.info("waiting_for_root_nodes_after_hard_restart")
            await consensus_monitor.wait_for_links_connecting_state(timeout=60.0)
            logger.info("root_nodes_restarted_with_genesis_event_config")
            
            # Node list preserved in GDB, no re-registration needed!
            
        except Exception as e:
            logger.error("root_nodes_genesis_failed", error=str(e))
            self.compose.down(volumes=False, remove_images=False)
            raise RuntimeError(f"ROOT nodes genesis failed: {e}") from e
        
        # =================================================================
        # PHASE 2: START MASTER NODES FOR ESBOCS GENESIS
        # =================================================================
        logger.info("=== PHASE 2: Start MASTER (ESBocs Genesis) ===")
        
        try:
            # ROOT nodes already restarted in PHASE 1 with:
            # - seed_mode=false
            # - static_genesis_event_hash set
            # - GDB node list preserved
            
            # Start MASTER nodes (have seed_mode=true in configs)
            master_services = [f"node-{nid}" for nid in master_node_ids]
            logger.info("starting_master_nodes", services=master_services, seed_mode=True)
            self.compose.up(services=master_services, detach=True, wait=False)
            
            # Wait for MASTER nodes to reach LINKS_CONNECTING state
            all_validator_nodes = root_nodes + master_nodes
            all_validator_nodes_dict = {f"node{n.node_id}": n for n in all_validator_nodes}
            consensus_monitor_all = NetworkConsensusMonitor(
                nodes=all_validator_nodes_dict,
                node_cli_path=self.node_cli_path
            )
            
            logger.info("waiting_for_all_validators_links_connecting")
            await consensus_monitor_all.wait_for_links_connecting_state(timeout=60.0)
            logger.info("all_validators_ready_for_registration")
            
            # Re-register full mesh node list (ROOT + MASTER)
            # Needed to ensure all 6 nodes are in each node's list before order creation
            logger.info("re_registering_full_validator_mesh")
            await self.genesis.registration_mgr.register_all_nodes_via_cli(all_validator_nodes)
            logger.info("validator_mesh_registered")
            
            # Soft reconnect to establish links quickly
            logger.info("soft_reconnect_for_consensus")
            await self.genesis.registration_mgr.soft_network_reconnect(all_validator_nodes, wait_for_links=True)
            logger.info("links_established_for_consensus")
            
            # Wait for network consensus with full node list
            logger.info("waiting_for_root_and_master_consensus")
            try:
                await consensus_monitor_all.wait_for_network_ready(timeout=120.0)
                logger.info("all_validator_nodes_ready")
            except TimeoutError as e:
                logger.error("validators_not_ready", error=str(e))
                raise RuntimeError(f"Validator nodes failed to reach consensus: {e}")
            
            # Disable seed_mode for MASTER nodes before creating orders
            # seed_mode=true can interfere with order creation
            logger.info("disabling_seed_mode_for_master_nodes")
            self.genesis.config_mgr.disable_seed_mode_in_configs(master_node_ids)
            
            # CRITICAL: Create validator orders for MASTER nodes
            # Must be done AFTER network is ready but BEFORE block creation
            # Orders are stored in GDB and automatically propagated
            logger.info("creating_validator_orders_for_master_nodes")
            for master_node in master_nodes:
                try:
                    container_name = f"cellframe-stage-node-{master_node.node_id}"
                    container = self.genesis.docker_client.containers.get(container_name)
                    await self.genesis.validator_mgr.create_validator_order(container, master_node)
                    logger.info("master_validator_order_created", node_id=master_node.node_id)
                except Exception as e:
                    logger.warning("failed_to_create_validator_order",
                                  node_id=master_node.node_id,
                                  error=str(e))
            
            # CRITICAL: Sync GDB to propagate validator orders across network
            # Orders are stored in local GDB but need sync to be visible on all nodes
            logger.info("syncing_validator_orders_across_network")
            await self.genesis.validator_mgr.sync_orders_across_network(all_validator_nodes)
            logger.info("gdb_synced_orders_propagated")
            
            # Verify that all nodes see all validator orders
            logger.info("verifying_validator_orders_visibility")
            await self.genesis.validator_mgr.verify_validator_orders(all_validator_nodes, expected_count=len(master_nodes))
            logger.info("validator_orders_verified_on_all_nodes")
            
            # CRITICAL: Sync zerochain to MASTER nodes (emission was created in Phase 1!)
            # Without this, master nodes can't see emission datum → tx_create fails
            logger.info("syncing_zerochain_to_master_nodes")
            await self.genesis.sync_mgr.sync_network(all_validator_nodes, chain_name="zerochain")
            logger.info("zerochain_synced_to_all_validators")
            
            # Create first TX on main chain → genesis block
            logger.info("creating_first_transaction_main_chain")
            tx_hash = await self.genesis.token_mgr.create_first_transaction(emission_hash, master_nodes=master_nodes)
            logger.info("first_transaction_created", hash=tx_hash[:16])
            
            # Wait for genesis block to be created (ESBocs consensus needs time)
            logger.info("waiting_for_main_genesis_block_creation")
            await self.genesis.sync_mgr.wait_for_first_block("main", timeout=60)
            logger.info("main_genesis_block_created")
            
            # Get genesis block hash
            main_genesis_hash = await self.genesis.config_mgr.get_genesis_block_hash("main")
            if not main_genesis_hash:
                raise RuntimeError("Failed to retrieve main genesis block hash")
            logger.info("main_genesis_block_hash", hash=main_genesis_hash[:16])
            
            # Update static_genesis_block in ALL configs
            logger.info("updating_static_genesis_block_in_all_configs")
            await self.genesis.config_mgr.update_static_genesis_in_config("main", main_genesis_hash, node_configs)
            logger.info("static_genesis_updated")
            
            # CRITICAL: HARD RESTART #2 - Apply ESBocs genesis block + disable seed_mode
            # Full container restart to reload configs from disk
            logger.info("=== HARD RESTART #2: After ESBocs Genesis Block ===")
            
            # Step 1: Disable seed_mode in ALL validator configs (write to disk)
            logger.info("disabling_seed_mode_for_all_validators")
            self.genesis.config_mgr.disable_seed_mode_in_configs(root_node_ids + master_node_ids)
            
            # Step 2: Hard restart ALL validators with config reload
            all_validator_services = root_services + master_services
            logger.info("hard_restarting_all_validators_for_config_reload")
            await lifecycle_mgr.hard_restart_with_config_reload(
                service_names=all_validator_services,
                compose_manager=self.compose,
                flush_timeout=60
            )
            
            # Step 3: Wait for ALL validators to come back online
            logger.info("waiting_for_all_validators_after_hard_restart")
            await consensus_monitor_all.wait_for_links_connecting_state(timeout=60.0)
            logger.info("all_validators_restarted_with_genesis_block_config")
            
            # Node list preserved in GDB, no re-registration needed!
            
            # Step 4: SOFT reconnect to quickly establish full mesh connectivity
            # After hard restart, soft offline/online helps links re-establish faster
            logger.info("soft_reconnect_after_hard_restart")
            await self.genesis.registration_mgr.soft_network_reconnect(all_validator_nodes, wait_for_links=True)
            logger.info("full_mesh_connectivity_established")
            
        except Exception as e:
            logger.error("master_nodes_genesis_failed", error=str(e))
            self.compose.down(volumes=False, remove_images=False)
            raise RuntimeError(f"MASTER nodes genesis failed: {e}") from e
        
        # =================================================================
        # PHASE 3: START FULL NODES
        # =================================================================
        logger.info("=== PHASE 3: Start FULL Nodes ===")
        
        try:
            # ROOT + MASTER already restarted in PHASE 2 with:
            # - seed_mode=false
            # - static_genesis_block set
            # - GDB node list preserved
            
            # Start FULL nodes
            full_services = [f"node-{nid}" for nid in full_node_ids]
            logger.info("starting_full_nodes", services=full_services)
            self.compose.up(services=full_services, detach=True, wait=False)
            
            # Wait for ALL nodes to be ready (ROOT + MASTER + FULL)
            logger.info("waiting_for_all_nodes_ready")
            
            # Use existing self.nodes (should include all nodes)
            final_consensus_monitor = NetworkConsensusMonitor(
                nodes=self.nodes,
                node_cli_path=self.node_cli_path
            )
            
            try:
                await final_consensus_monitor.wait_for_network_ready(timeout=150.0)
                logger.info("all_nodes_ready_for_snapshot")
            except TimeoutError as e:
                logger.error("full_network_not_ready", error=str(e))
                raise RuntimeError(f"Full network failed to reach consensus: {e}")
            
        except Exception as e:
            logger.error("full_nodes_startup_failed", error=str(e))
            self.compose.down(volumes=False, remove_images=False)
            raise RuntimeError(f"FULL nodes startup failed: {e}") from e
        
        # =================================================================
        # PHASE 4: NODE ALIASES REGISTRATION
        # =================================================================
        logger.info("=== PHASE 4: Node Aliases Registration ===")
        
        try:
            # Register node aliases in GDB
            # Node registration via CLI already done in PHASE 1 (pre-populated for all nodes)
            await self.genesis.registration_mgr.register_node_aliases(node_configs)
            logger.info("node_aliases_registered")
        except Exception as e:
            logger.error("node_alias_registration_failed", error=str(e))
            # Non-critical - continue
        
        # PHASE 5: Wait for network consensus
        logger.info("=== PHASE 5: Network Consensus Verification ===")
        from ..monitoring.network_consensus import NetworkConsensusMonitor
        
        consensus_monitor = NetworkConsensusMonitor(
            nodes=self.nodes,
            node_cli_path=self.node_cli_path,
            network_name=self.topology.network.name,
            check_interval=2.0
        )
        
        try:
            await consensus_monitor.wait_for_network_ready(timeout=150.0)  # 150s for 8-node topology
            logger.info("network_consensus_achieved")
        except TimeoutError as e:
            logger.error("network_consensus_timeout_critical",
                        error=str(e),
                        note="Network failed to reach consensus - stopping all containers")
            
            # Collect metrics for diagnosis
            try:
                metrics = await consensus_monitor.collect_all_metrics()
                logger.error("final_network_state_before_shutdown",
                           metrics={
                               node_id: {
                                   "online": m.is_online,
                                   "error": m.error,
                                   "node_list_count": m.node_list_count,
                                   "blocks": m.main_chain_blocks,
                               }
                               for node_id, m in metrics.items()
                           })
            except Exception as diag_error:
                logger.warning("failed_to_collect_diagnostic_metrics",
                             error=str(diag_error))
            
            # Stop all containers
            logger.info("stopping_failed_network")
            try:
                self.compose.down(volumes=False, remove_images=False)
            except Exception as stop_error:
                logger.warning("failed_to_stop_network",
                             error=str(stop_error))
            
            # Re-raise with clear message
            raise RuntimeError(
                f"Network failed to reach consensus within 60s. "
                f"All nodes must be online with synchronized node lists and chains. "
                f"Check logs above for details. Network has been stopped."
            ) from e
        
        # OPTIMIZATION: Create pristine snapshot for fast suite isolation
        # Pause containers → Create snapshot → Unpause
        # This way first suite can use already running network immediately
        # and snapshot remains pristine for subsequent suites
        if self.suite_isolation_config.get('auto_create_on_startup', True):
            if self.snapshot_manager.mode != SnapshotMode.DISABLED:
                logger.info("creating_initial_clean_snapshot_with_pause")
                containers_paused = False
                try:
                    # Pause all containers to freeze state
                    logger.info("pausing_containers_for_snapshot")
                    self.compose.pause()
                    containers_paused = True
                    
                    # =================================================================
                    # PHASE 6: CREATE CLEAN SNAPSHOT
                    # =================================================================
                    logger.info("=== PHASE 6: Creating Clean Snapshot ===")
                    
                    # Create snapshot of paused state
                    await self.create_clean_snapshot()
                    logger.info("initial_snapshot_created")
                    
                    # Unpause containers - ready for first suite
                    logger.info("unpausing_containers")
                    self.compose.unpause()
                    containers_paused = False
                    logger.info("containers_unpaused_ready_for_first_suite")
                    
                except Exception as e:
                    # Only unpause if we actually paused
                    if containers_paused:
                        try:
                            self.compose.unpause()
                        except:
                            pass
                    logger.warning("initial_snapshot_creation_failed",
                                  error=str(e),
                                  note="Will fallback to traditional cleanup")
        
        logger.info("network_started",
                   nodes=len(self.nodes),
                   topology=self.topology.network.name)
    
    async def stop(self, remove_volumes: bool = False) -> None:
        """
        Stop the test network.
        
        Args:
            remove_volumes: Remove data volumes
        """
        logger.info("stopping_network", remove_volumes=remove_volumes)
        
        # Stop Docker services
        self.compose.down(volumes=remove_volumes)
        
        logger.info("network_stopped")
    
    async def restart(self, node_name: Optional[str] = None) -> None:
        """
        Restart network or specific node.
        
        Args:
            node_name: Node to restart (None = all)
        """
        if node_name:
            logger.info("restarting_node", node=node_name)
            # Restart specific container
            containers = self.compose.ps()
            for container in containers:
                service = container.labels.get("com.docker.compose.service")
                if service == node_name:
                    container.restart()
                    logger.info("node_restarted", node=node_name)
                    return
            
            logger.warning("node_not_found", node=node_name)
        else:
            logger.info("restarting_network")
            await self.stop(remove_volumes=False)
            await self.start(rebuild=False, wait_ready=True)
    
    async def get_status(self) -> Dict[str, any]:
        """
        Get network status.
        
        Returns:
            Status information dict
        """
        logger.debug("getting_network_status")
        
        # Get container status
        service_status = self.compose.get_service_status()
        
        # Get health status via JSON-RPC (CLI)
        health_status = {}
        for node_name, config in self.nodes.items():
            try:
                # Convert node_name to container name (node1 -> node-1)
                if node_name.startswith('node'):
                    container_name = f"cellframe-stage-node-{node_name[4:]}"
                else:
                    container_name = f"cellframe-stage-{node_name}"
                
                container = self.compose.client.containers.get(container_name)
                cli_result = container.exec_run(
                    'cellframe-node-cli net get status -net stagenet',
                    demux=False
                )
                
                if cli_result.exit_code == 0:
                    output = cli_result.output.decode("utf-8")
                    # Parse state
                    current_state = "unknown"
                    for line in output.split('\n'):
                        if 'current:' in line and 'NET_STATE_' in line:
                            parts = line.split(':', 1)
                            if len(parts) == 2:
                                current_state = parts[1].strip()
                                break
                    
                    health_status[node_name] = {
                        "healthy": current_state == "NET_STATE_ONLINE",
                        "state": current_state,
                        "response_time_ms": 0,  # Not applicable for CLI
                    }
                else:
                    health_status[node_name] = {
                        "healthy": False,
                        "state": "unavailable",
                        "response_time_ms": 0,
                    }
            except Exception as e:
                logger.warning("failed_to_get_node_health", node=node_name, error=str(e))
                health_status[node_name] = {
                    "healthy": False,
                    "state": "error",
                    "response_time_ms": 0,
                }
        
        # Build nodes array with combined info
        nodes_data = []
        for node_name, config in self.nodes.items():
            # Get container status
            container_status = service_status.get(node_name, {})
            # Get health status
            health = health_status.get(node_name, {})
            
            nodes_data.append({
                "name": node_name,
                "role": config.role,
                "container_status": container_status.get("status", "unknown"),
                "health_status": health.get("state", "unknown"),
                "healthy": health.get("healthy", False),
                "rpc_port": config.rpc_port,
                "p2p_port": config.p2p_port,
            })
        
        return {
            "topology": self.topology_name,
            "network_name": self.topology.network.name,
            "total_nodes": len(self.nodes),
            "nodes": nodes_data,
            "containers": service_status,
            "health": health_status,
        }
    
    async def _wait_for_network_ready(self) -> None:
        """
        Wait for all nodes to be ready.
        
        Uses timeout from config [timeouts] section.
        """
        timeout = self.timeouts.get('health_check', 300)
        logger.info("waiting_for_network_ready", timeout=timeout)
        
        # Wait for Docker containers and nodes to reach ONLINE state
        # This is now handled entirely by compose.wait_for_services()
        # which uses CLI to check node state
        self.compose.wait_for_services(timeout=int(timeout))
        
        logger.info("network_ready", nodes=len(self.nodes))
    
    def get_node_logs(
        self,
        node_name: str,
        tail: int = 100,
        follow: bool = False,
    ) -> str:
        """
        Get logs for a node.
        
        Args:
            node_name: Node identifier
            tail: Number of lines from end
            follow: Follow log output
            
        Returns:
            Log output
        """
        logger.debug("fetching_logs", node=node_name, tail=tail)
        
        return self.compose.logs(node_name, follow=follow, tail=tail)
    
    def exec_in_node(
        self,
        node_name: str,
        command: List[str],
    ) -> tuple[int, str]:
        """
        Execute command in node container.
        
        Args:
            node_name: Node identifier
            command: Command to execute
            
        Returns:
            Tuple of (exit_code, output)
        """
        logger.debug("executing_in_node",
                    node=node_name,
                    command=" ".join(command))
        
        return self.compose.exec(node_name, command)
    
    def list_nodes(self) -> List[Dict[str, any]]:
        """
        List all configured nodes.
        
        Returns:
            List of node information dicts
        """
        return [
            {
                "name": name,
                "id": config.node_id,
                "role": config.role,
                "type": config.node_type,
                "rpc_port": config.rpc_port,
                "p2p_port": config.p2p_port,
                "ip": config.ip_address,
            }
            for name, config in self.nodes.items()
        ]
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        await self.health_checker.close()
    
    async def create_clean_snapshot(self, name: Optional[str] = None) -> bool:
        """
        Create a snapshot of current clean environment state.
        
        Should be called after network is fully initialized and ready,
        before any tests are run.
        
        Args:
            name: Optional snapshot name (defaults to config snapshot_name)
            
        Returns:
            True if snapshot created successfully
        """
        snapshot_name = name or self.suite_isolation_config.get('snapshot_name', 'clean_state')
        
        logger.info("creating_clean_snapshot",
                   name=snapshot_name,
                   mode=self.snapshot_manager.mode.value)
        
        result = await self.snapshot_manager.create_snapshot(snapshot_name)
        
        if result and self.suite_isolation_config.get('auto_cleanup', True):
            # Cleanup old snapshots
            keep_count = self.suite_isolation_config.get('keep_snapshot_count', 5)
            await self.snapshot_manager.cleanup_old_snapshots(keep_count)
        
        return result
    
    async def restore_clean_state(self, name: Optional[str] = None) -> bool:
        """
        Restore environment to clean snapshot state.
        
        This replaces the current clean_test_data() approach with snapshot restoration,
        providing much faster suite isolation.
        
        Args:
            name: Optional snapshot name (defaults to config snapshot_name)
            
        Returns:
            True if restore successful
        """
        snapshot_name = name or self.suite_isolation_config.get('snapshot_name', 'clean_state')
        
        logger.info("restoring_clean_state",
                   name=snapshot_name,
                   mode=self.snapshot_manager.mode.value)
        
        # Special case for 'recreate' mode - use traditional cleanup
        if self.snapshot_manager.mode == SnapshotMode.RECREATE:
            logger.info("recreate_mode_using_clean_test_data")
            await self.clean_test_data()
            return True
        
        # For other modes, restore from snapshot
        # CRITICAL: Stop containers before restore to avoid file conflicts
        logger.info("stopping_containers_before_snapshot_restore")
        await self.stop(remove_volumes=False)
        
        # Restore snapshot with containers stopped
        result = await self.snapshot_manager.restore_snapshot(snapshot_name)
        
        if not result:
            logger.warning("snapshot_restore_failed_fallback_to_cleanup")
            # Restart containers even if restore failed
            logger.info("starting_containers_after_failed_restore")
            await self.start(rebuild=False, wait_ready=True)
            # Only try cleanup if containers are running
            if self.compose and self.compose.is_running():
                await self.clean_test_data()
            else:
                logger.warning("containers_not_running_skipping_cleanup")
            return False
        
        # Restart containers with restored data
        logger.info("starting_containers_after_snapshot_restore")
        await self.start(rebuild=False, wait_ready=True)
        
        return result
    
    async def clean_test_data(self) -> None:
        """
        Clean test data from all nodes (traditional approach).
        
        This is the original cleanup method, now used as fallback or for 'recreate' mode.
        Removes user-generated data while preserving system files.
        """
        logger.info("cleaning_test_data_traditional_method")
        
        for node_name in self.nodes.keys():
            try:
                # Execute cleanup inside container to avoid permission issues
                cleanup_script = """
                # Clean user-generated data
                rm -f /opt/cellframe-node/var/lib/wallet/*.dwallet 2>/dev/null || true
                rm -rf /opt/cellframe-node/var/lib/chains/* 2>/dev/null || true
                rm -rf /opt/cellframe-node/var/lib/gdb/* 2>/dev/null || true
                rm -f /opt/cellframe-node/var/log/*.log 2>/dev/null || true
                
                # Preserve:
                # - /opt/cellframe-node/var/lib/ca/ (validator certificates)
                # - /opt/cellframe-node/var/run/ (PID files, sockets)
                
                echo "Cleanup complete for $(hostname)"
                """
                
                exit_code, output = self.compose.exec(
                    node_name,
                    ["sh", "-c", cleanup_script]
                )
                
                if exit_code == 0:
                    logger.debug("node_data_cleaned", node=node_name)
                else:
                    logger.warning("node_cleanup_failed",
                                  node=node_name,
                                  exit_code=exit_code,
                                  output=output)
            except Exception as e:
                logger.error("node_cleanup_error",
                            node=node_name,
                            error=str(e))
    
    def _clean_node_data(self):
        """
        Clean node data directories on host before creating pristine snapshot.
        
        This method removes and recreates data directories mounted into containers,
        ensuring that wallets, chains, and other runtime data from previous runs
        don't pollute the snapshot.
        
        Called before pause→snapshot→unpause to guarantee pristine state.
        
        Implementation: Uses temporary Docker container (Alpine) to clean files.
        This ensures proper permissions for root-owned files created by node containers.
        """
        cache_dir = self.paths_config.get('cache_dir', '../testing/cache')
        cache_path = (self.base_path / cache_dir).resolve()
        data_dir = cache_path / "data"
        
        if not data_dir.exists():
            logger.debug("node_data_dir_not_exists", path=str(data_dir))
            return
        
        logger.info("removing_node_data_directories", path=str(data_dir))
        
        # Use Docker container to remove files (handles root-owned files)
        try:
            self.compose.clean_cache_data(cache_path)
            logger.info("node_data_removed")
        except Exception as e:
            logger.error("failed_to_remove_node_data", error=str(e))
            raise
        
        # Recreate empty data directory structure for each node
        data_dir.mkdir(parents=True, exist_ok=True)
        
        for node_id in range(1, len(self.nodes) + 1):
            node_data_path = data_dir / f"node{node_id}"
            node_data_path.mkdir(parents=True, exist_ok=True)
            logger.debug("recreated_node_data_dir", node_id=node_id, path=str(node_data_path))
        
        logger.info("node_data_cleaned_and_recreated", nodes=len(self.nodes))

