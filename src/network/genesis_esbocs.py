"""
ESBocs consensus genesis management for Cellframe stagenet.

Handles ESBocs consensus initialization with PoS stake delegation:
1. Regenerate configs with only first master node in validators_addrs
2. Create wallets for ALL master nodes
3. Transfer tokens from ROOT to MASTER nodes (on zerochain)
4. Delegate keys via srv_stake on zerochain (NO orders needed)
5. Restart → ESBocs loads delegated keys from stake service
6. Create genesis block with ALL master nodes as validators
7. Update configs with genesis block and disable seed_mode
"""

import asyncio
import re
import time
from pathlib import Path
from typing import List, Optional, Dict

import docker

from .genesis_base import BaseGenesisManager
from .models import NodeConfig
from ..utils.logger import get_logger
from ..monitoring.waiter.validator_waiters import (
    StakeServiceReadyWaiter,
    ESBocsConsensusActiveWaiter,
)
from ..monitoring.waiter.sync_waiters import FirstBlockWaiter
from ..monitoring.waiter.gdb_waiters import GDBClustersReadyWaiter
from ..monitoring.waiter.token_waiters import TokenInMempoolWaiter
from ..monitoring.waiter.genesis_waiters import (
    MasterContainersRunningWaiter,
    CLIReadyWaiter,
    TransactionProcessedWaiter,
    GDBSyncCompleteWaiter,
    DelegationsSyncedWaiter,
)
from ..monitoring.checker.config_checkers import verify_zerochain_config
from ..monitoring.checker.ledger_checkers import LedgerTransactionChecker
from ..monitoring.waiters import LedgerTransactionWaiter


logger = get_logger(__name__)


class ESBocsGenesisManager(BaseGenesisManager):
    """
    Manages ESBocs consensus genesis initialization with PoS.
    
    Responsibilities:
    - Regenerate chain configs with single validator for bootstrap
    - Create wallets for ALL MASTER nodes
    - Transfer tokens from ROOT to MASTER (on zerochain)
    - Delegate keys via srv_stake on zerochain (PoS without orders)
    - Restart to load delegations into stake service
    - Wait for ESBocs consensus with ALL master validators
    - Create genesis block
    - Update configs and finalize
    """
    
    def __init__(self, base_path: Path, network_name: str = "stagenet", config_path: Path = None):
        """
        Initialize ESBocs genesis manager.
        
        Args:
            base_path: Base path to stage-env directory
            network_name: Network name (default: stagenet)
            config_path: Optional path to stage-env.cfg
        """
        super().__init__(base_path, network_name, config_path)
        
        # Import managers (to avoid circular imports)
        from .genesis import GenesisInitializer
        self.genesis = GenesisInitializer(base_path, network_name, config_path)
    
    async def regenerate_configs_with_all_master_validators(
        self,
        all_validator_nodes: List[NodeConfig],
        master_nodes: List[NodeConfig],
        root_nodes: List[NodeConfig] = None  # CRITICAL: Need root nodes to read static_genesis_event after snapshot restore
    ) -> None:
        """
        Regenerate chain configs with ALL master nodes as validators.
        
        Uses ConfigGenerator to properly regenerate all chain configs
        (main.cfg, zerochain.cfg) with all master validators.
        
        Args:
            all_validator_nodes: List of all validator nodes (for root_nodes_addrs)
            master_nodes: List of ALL master nodes (will be validators)
            root_nodes: List of ROOT nodes (used to read static_genesis_event after snapshot restore)
        """
        logger.info("regenerating_chain_configs_with_all_master_validators",
                   master_count=len(master_nodes))
        
        # Collect addresses from ALL master nodes
        certs_cache = self.base_path.parent / "testing" / "cache" / "certs"
        master_addrs = []
        
        for master_node in master_nodes:
            validator_addr_file = certs_cache / f"node{master_node.node_id}" / "validator_addr.txt"
        
            if not validator_addr_file.exists():
                raise RuntimeError(
                    f"validator_addr.txt not found for node {master_node.node_id}. "
                    f"Expected at: {validator_addr_file}. "
                    f"Certificates must be generated before regenerating configs."
                )
            
            master_addr = validator_addr_file.read_text().strip()
            if not master_addr:
                raise RuntimeError(
                    f"validator_addr.txt is empty for node {master_node.node_id}"
                )
            
            master_addrs.append(master_addr)
            logger.info("read_validator_addr_from_file",
                       node_id=master_node.node_id,
                       address=master_addr)
        
        # CRITICAL: Read ALL parameters from ROOT node configs AFTER snapshot restore
        # ROOT nodes have correct static_genesis_event after snapshot restore
        # Use first ROOT node if available, otherwise fall back to first validator node
        if root_nodes and len(root_nodes) > 0:
            config_node = root_nodes[0]
            logger.info("reading_configs_from_root_node_after_snapshot_restore",
                       node_id=config_node.node_id,
                       note="Using ROOT node config to read static_genesis_event after snapshot restore")
        else:
            config_node = all_validator_nodes[0]
            logger.warning("no_root_nodes_using_first_validator_node",
                          node_id=config_node.node_id,
                          note="No root nodes provided, using first validator node")
        
        cache_path = self.genesis.base_path.parent / "testing" / "cache"
        zerochain_config_path = cache_path / "configs" / f"node{config_node.node_id}" / "network" / self.network_name / "zerochain.cfg"
        main_config_path = cache_path / "configs" / f"node{config_node.node_id}" / "network" / self.network_name / "main.cfg"
        
        static_genesis_event = None
        fee_addr = None
        min_validators_count = 2  # Default: 2/3 consensus for 3 validators
        
        # Read static_genesis_event from zerochain.cfg using centralized config manager
        if zerochain_config_path.exists():
            from ..config.manager import get_config_loader
            config_loader = get_config_loader()
            config = config_loader.load_config_file(zerochain_config_path)
            
            if 'dag' in config and 'static_genesis_event' in config['dag']:
                static_genesis_event = config['dag']['static_genesis_event'].strip()
                if static_genesis_event:
                    logger.info("preserving_static_genesis_event_before_regenerate",
                              hash=static_genesis_event[:16],
                              node_id=config_node.node_id,
                              note="Reading static_genesis_event from ROOT node config after snapshot restore")
                else:
                    logger.warning("static_genesis_event_empty_in_config",
                                 node_id=config_node.node_id,
                                 note="static_genesis_event is empty in config")
            else:
                logger.error("static_genesis_event_not_found_in_config",
                           node_id=config_node.node_id,
                           config_path=str(zerochain_config_path),
                           note="CRITICAL: static_genesis_event not found in config after snapshot restore!")
        else:
            logger.error("zerochain_config_not_found",
                       node_id=config_node.node_id,
                       config_path=str(zerochain_config_path),
                       note="CRITICAL: Zerochain config not found after snapshot restore!")
        
        # Read fee_addr and min_validators_count from main.cfg using centralized config manager
        if main_config_path.exists():
            from ..config.manager import get_config_loader
            config_loader = get_config_loader()
            config = config_loader.load_config_file(main_config_path)
            
            if 'esbocs' in config:
                if 'fee_addr' in config['esbocs']:
                    fee_addr = config['esbocs']['fee_addr'].strip()
                    if fee_addr:
                        logger.info("preserving_fee_addr_before_regenerate",
                                  fee_addr=fee_addr[:16],
                                  node_id=config_node.node_id,
                                  note="Reading fee_addr from ROOT node config")
                
                if 'min_validators_count' in config['esbocs']:
                    try:
                        min_validators_count = int(config['esbocs']['min_validators_count'])
                        logger.info("preserving_min_validators_count_before_regenerate",
                                  min_validators_count=min_validators_count,
                                  node_id=config_node.node_id,
                                  note="Reading min_validators_count from ROOT node config")
                    except ValueError:
                        logger.warning("invalid_min_validators_count_in_config",
                                     node_id=config_node.node_id,
                                     note="Using default value 2")
        
        # CRITICAL: Fail fast if static_genesis_event is not found
        if not static_genesis_event:
            raise RuntimeError(
                f"CRITICAL: static_genesis_event not found in ROOT node {config_node.node_id} config after snapshot restore! "
                f"Config path: {zerochain_config_path}. "
                f"Without static_genesis_event, genesis event won't load and UTXO won't be indexed!"
            )
        
        # Use ConfigGenerator to regenerate chain configs with ALL master validators
        from ..config.generator import ConfigGenerator
        config_generator = ConfigGenerator(self.base_path)
        
        # Format: [addr1,addr2,addr3]
        custom_validators_addrs = f"[{','.join(master_addrs)}]"
        
        config_generator.regenerate_chain_configs_with_custom_validators(
            nodes=all_validator_nodes,
            network_name=self.network_name,
            custom_validators_addrs=custom_validators_addrs,
            min_validators_count=min_validators_count,  # From config
            static_genesis_event=static_genesis_event,  # CRITICAL: Preserve!
            fee_addr=fee_addr  # CRITICAL: Preserve!
        )
        
        logger.info("chain_configs_regenerated_with_all_master_validators",
                   master_count=len(master_nodes),
                   validators_addrs=custom_validators_addrs[:60])
    
    async def initialize_esbocs_genesis_with_pos_delegation(
        self,
        master_nodes: List[NodeConfig],
        all_validator_nodes: List[NodeConfig],
        node_configs: List[NodeConfig],
        root_nodes: List[NodeConfig],
        emission_hash: str,
        compose_manager,
        state_manager,
        lifecycle_manager,
        consensus_monitor,
        topology
    ) -> None:
        """
        Initialize ESBocs genesis with PoS stake delegation (ALL master validators).
        
        Args:
            master_nodes: List of MASTER nodes
            all_validator_nodes: List of all validator nodes (ROOT + MASTER)
            node_configs: List of all node configurations
            root_nodes: List of ROOT nodes
            emission_hash: Emission hash from zerochain
            compose_manager: Docker compose manager
            state_manager: Node state manager
            lifecycle_manager: Node lifecycle manager
            consensus_monitor: Network consensus monitor
            topology: Network topology
            
        Raises:
            RuntimeError: If genesis initialization fails
        """
        logger.info("=== PHASE 2: Start MASTER (ESBocs Genesis with PoS - 3 Validators, 2/3 Consensus) ===")
        
        # Store emission_hash for later use in ledger checks
        self.emission_hash = emission_hash
        
        try:
            # Step 0: CRITICAL - Regenerate chain configs with ALL master validators
            # In PoS we can use all validators from the start (emission controlled by ROOT on zerochain)
            first_master_node = master_nodes[0]
            logger.info("regenerating_chain_configs_with_all_masters_before_starting",
                       master_count=len(master_nodes))
            await self.regenerate_configs_with_all_master_validators(
                all_validator_nodes,
                master_nodes,  # ALL master nodes
                root_nodes=root_nodes  # CRITICAL: Pass root nodes to read static_genesis_event after snapshot restore
            )
            logger.info("chain_configs_regenerated_with_all_validators")
            
            # DIAGNOSTIC: Verify generated config is correct
            logger.info("diagnostic_verifying_generated_main_cfg")
            first_master_cfg = self.base_path.parent / "testing" / "cache" / "configs" / f"node{first_master_node.node_id}" / "network" / self.network_name / "main.cfg"
            if first_master_cfg.exists():
                cfg_content = first_master_cfg.read_text()
                import re
                validators_match = re.search(r'validators_addrs=(.+)', cfg_content)
                if validators_match:
                    validators_value = validators_match.group(1).strip()
                    logger.info("diagnostic_validators_addrs_in_generated_config",
                               node_id=first_master_node.node_id,
                               validators_addrs=validators_value,
                               length=len(validators_value),
                               has_brackets=validators_value.startswith('[') and validators_value.endswith(']'))
                else:
                    logger.error("diagnostic_validators_addrs_not_found_in_generated_config",
                               node_id=first_master_node.node_id)
            
            # Step 1: Enable seed_mode for MASTER nodes (required for genesis block creation)
            # CRITICAL: Only MASTER nodes need seed_mode=true for PHASE 2 (genesis block)
            # ROOT nodes already have seed_mode=false (disabled after genesis event in PHASE 1)
            logger.info("enabling_seed_mode_for_master_nodes_phase2")
            master_node_ids = [n.node_id for n in master_nodes]
            self.genesis.config_mgr.enable_seed_mode_in_configs(master_node_ids)
            logger.info("seed_mode_enabled_for_master_nodes",
                       master_nodes=master_node_ids,
                       note="MASTER nodes will start with seed_mode=true for genesis block creation")
            
            # Step 2: Start MASTER nodes with seed_mode=true
            master_services = [f"node-{n.node_id}" for n in master_nodes]
            logger.info("starting_master_nodes", 
                       services=master_services, 
                       master_seed_mode=True,
                       note="MASTER seed_mode=true for genesis block creation")
            
            compose_manager.up(services=master_services, detach=True, wait=False)
            logger.info("master_nodes_containers_started")
            
            # Wait for containers and CLI
            waiter_containers = MasterContainersRunningWaiter(
                docker_client=self.docker_client,
                master_nodes=master_nodes,
                poll_interval=1.0
            )
            await waiter_containers.wait(timeout=30.0)
            logger.info("waiting_for_cli_server_ready")
            # Wait for CLI to be ready on all master nodes
            for master_node in master_nodes:
                waiter_cli = CLIReadyWaiter(
                    exec_cli=self.genesis._exec_cli,
                    node_id=master_node.node_id,
                    network_name=self.network_name,
                    poll_interval=0.5
                )
                await waiter_cli.wait(timeout=30.0)
            logger.info("cli_servers_ready_on_all_master_nodes")
            
            # Step 3: Sync node list from ROOT nodes
            logger.info("syncing_node_list_from_root_nodes_via_bootstrap")
            for master_node in master_nodes:
                for attempt in range(3):
                    try:
                        exit_code, stdout, stderr = self.genesis._exec_cli(
                            master_node.node_id,
                            f"net -net {self.network_name} go sync",
                            check_output=False
                        )
                        if exit_code == 0:
                            break
                        if attempt < 2:
                            await asyncio.sleep(1.0)
                    except Exception:
                        if attempt < 2:
                            await asyncio.sleep(1.0)
            
            # Wait for GDB sync to complete
            waiter_gdb_sync = GDBSyncCompleteWaiter(
                exec_cli=self.genesis._exec_cli,
                nodes=master_nodes,
                network_name=self.network_name,
                poll_interval=2.0
            )
            await waiter_gdb_sync.wait(timeout=30.0)
            
            # Diagnostic: Check if containers are running before going online
            logger.info("diagnostic_checking_master_containers_status")
            for master_node in master_nodes:
                try:
                    container_name = f"cellframe-stage-node-{master_node.node_id}"
                    container = self.genesis.docker_client.containers.get(container_name)
                    container.reload()
                    logger.info("master_container_status",
                               node_id=master_node.node_id,
                               status=container.status)
                    
                    if container.status != 'running':
                        raise RuntimeError(
                            f"Container for node {master_node.node_id} is not running. "
                            f"Status: {container.status}"
                        )
                except docker.errors.NotFound:
                    raise RuntimeError(
                        f"Container for node {master_node.node_id} not found. "
                        f"Expected container name: {container_name}"
                    )
            
            # CRITICAL: Explicitly bring MASTER nodes online after sync
            # After sync, nodes don't automatically transition to ONLINE state
            logger.info("bringing_master_nodes_online_after_sync")
            for master_node in master_nodes:
                try:
                    logger.info("executing_net_go_online", node_id=master_node.node_id)
                    exit_code, stdout, stderr = self.genesis._exec_cli(
                        master_node.node_id,
                        f"net -net {self.network_name} go online",
                        check_output=False
                    )
                    logger.info("net_go_online_result",
                               node_id=master_node.node_id,
                               exit_code=exit_code,
                               stdout_preview=stdout[:200] if stdout else "empty",
                               stderr_preview=stderr[:200] if stderr else "empty")
                    
                    if exit_code == 0:
                        logger.info("master_node_online_command_successful", node_id=master_node.node_id)
                    else:
                        logger.error("master_node_online_command_failed",
                                   node_id=master_node.node_id,
                                   exit_code=exit_code,
                                   stderr=stderr if stderr else "empty")
                        raise RuntimeError(
                            f"Failed to bring node {master_node.node_id} online. "
                            f"Exit code: {exit_code}, stderr: {stderr}"
                        )
                except Exception as e:
                    logger.error("failed_to_bring_master_node_online",
                               node_id=master_node.node_id,
                               error=str(e))
                    raise
            
            # Wait for nodes to transition to ONLINE (state_manager handles this intelligently)
            await state_manager.wait_for_nodes_online(master_nodes, timeout=60.0)
            
            # CRITICAL: Wait for GDB clusters initialization
            # GDB cluster for "stagenet.service.orders" is created when stake service initializes
            # This happens during network load, AFTER chains are loaded
            # If we create order before cluster is initialized, dap_global_db_set_sync will fail
            logger.info("waiting_for_gdb_clusters_initialization")
            waiter_gdb_clusters = GDBClustersReadyWaiter(
                exec_cli=self.genesis._exec_cli,
                node_id=first_master_node.node_id,
                network_name=self.network_name,
                poll_interval=1.0
            )
            await waiter_gdb_clusters.wait(timeout=10.0)
            
            # Step 4: Register all nodes via CLI (only ROOT nodes can be registered this way)
            # MASTER nodes will get node list via GDB sync from Step 3 (net go sync)
            # Note: MASTER nodes may show "Can't find state" during registration - this is expected
            # because they get node list via GDB sync, not CLI registration
            logger.info("registering_all_nodes_via_cli")
            await self.genesis.registration_mgr.register_all_nodes_via_cli(all_validator_nodes)
            logger.info("master_nodes_registered")
            
            # Step 5: Verify links are established (they should already be established after Step 3)
            # Links are established when nodes go online after sync
            logger.info("verifying_links_are_established")
            from ..monitoring.network_consensus import NetworkConsensusMonitor
            monitor = NetworkConsensusMonitor(
                nodes={f"node{n.node_id}": n for n in all_validator_nodes},
                network_name=self.network_name
            )
            try:
                await monitor.wait_for_links_established(timeout=30.0)
                logger.info("links_verified_established")
            except TimeoutError:
                logger.warning("links_verification_timeout",
                            note="Links may not be fully established, but proceeding")
            
            # Step 6: Create wallets for ALL MASTER nodes (for PoS stake delegation on zerochain)
            # CRITICAL: Master wallets are NOW created in PHASE 2 (not in PHASE 1 snapshot)
            # REASON: In PHASE 1 after hard restart, SDK doesn't index UTXO in ledger_items
            # In PHASE 2 after snapshot restore, SDK is in load_mode and properly indexes UTXO
            # This allows wallet creation and token transfers to work correctly
            logger.info("creating_or_verifying_master_wallets",
                       note="Master wallets will be created in PHASE 2 (or verified if exist from snapshot)")
            master_wallets: Dict[int, str] = {}  # node_id -> wallet_address
            
            for master_node in master_nodes:
                validator_idx = master_node.node_id - 4  # node4→0, node5→1, node6→2
                cert_name = f"pvt.{self.network_name}.master.{validator_idx}"
                wallet_name = f"{self.network_name}_master_{validator_idx}"
                
                # Check if wallet exists from old snapshot (legacy support)
                # NEW: Wallets are now created in PHASE 2, not in PHASE 1 snapshot
                exit_code, stdout, stderr = self.genesis._exec_cli(
                    master_node.node_id,
                    f"wallet list",
                    check_output=False
                )
                
                # Parse wallet address from list if exists
                # Format: wallet: stagenet_master_0\n  address: WkojSeUjApyYYy5X...
                wallet_section_match = re.search(
                    rf'wallet["\']?\s*:\s*{re.escape(wallet_name)}.*?address["\']?\s*:\s*([A-Za-z0-9]+)',
                    stdout,
                    re.IGNORECASE | re.DOTALL
                )
                
                if wallet_section_match:
                    # Wallet exists (from old snapshot or already created)
                    wallet_addr = wallet_section_match.group(1)
                    master_wallets[master_node.node_id] = wallet_addr
                    logger.info("master_wallet_found",
                               node_id=master_node.node_id,
                               wallet_name=wallet_name,
                               address=wallet_addr[:16],
                               note="Wallet already exists")
                else:
                    # Wallet doesn't exist - create it now (normal flow for new architecture)
                    logger.info("creating_master_wallet_in_phase2",
                                 node_id=master_node.node_id,
                                 wallet_name=wallet_name,
                                 note="Creating master wallet in PHASE 2 where SDK properly indexes UTXO")
                    wallet_addr = await self.create_wallet(
                        master_node.node_id,
                        wallet_name,
                        cert_name
                    )
                    master_wallets[master_node.node_id] = wallet_addr
                    logger.info("master_wallet_created_in_phase2",
                               node_id=master_node.node_id,
                               wallet_name=wallet_name,
                               address=wallet_addr[:16])
            
            # Step 6: Transfer tokens from fee_collector wallet to master nodes on zerochain
            # CRITICAL: In PHASE 1, emission was transferred to fee_collector wallet before snapshot creation.
            # After snapshot restore, fee_collector wallet is restored with tokens from snapshot.
            # In PHASE 2, SDK is in load_mode after snapshot restore, so UTXO are properly indexed.
            # This allows transfers to work correctly (unlike PHASE 1 where UTXO weren't indexed).
            first_root_node = root_nodes[0]
            emission_wallet_name = "fee_collector"  # Wallet created in PHASE 1
            
            logger.info("using_fee_collector_wallet_balance_from_snapshot",
                       wallet_name=emission_wallet_name,
                       note="fee_collector wallet restored from PHASE 1 snapshot. "
                            "In PHASE 2, SDK is in load_mode so UTXO are properly indexed for transfers.")
            
            # CRITICAL: After snapshot restore, verify configs and check node logs BEFORE transfer
            # This helps diagnose why UTXO might not be indexed
            logger.info("verifying_configs_and_logs_after_snapshot_restore",
                       note="CRITICAL: Verifying zerochain configs and checking node logs for genesis event loading")
            
            # Check configs on ALL root nodes
            config_issues = []
            for root_node in root_nodes:
                node_id = root_node.node_id
                try:
                    static_genesis_hash, is_static_genesis, seed_mode = await verify_zerochain_config(
                        base_path=self.genesis.base_path,
                        node_id=node_id,
                        network_name=self.network_name,
                        config_path=self.config_path
                    )
                    
                    if not static_genesis_hash:
                        config_issues.append(f"node{node_id}: static_genesis_event is NOT SET")
                    elif not is_static_genesis:
                        config_issues.append(f"node{node_id}: is_static_genesis_event=false but static_genesis_event={static_genesis_hash[:16]}")
                    else:
                        logger.info("config_check_passed",
                                   node_id=node_id,
                                   static_genesis_hash=static_genesis_hash[:16],
                                   seed_mode=seed_mode)
                except RuntimeError as config_err:
                    config_issues.append(f"node{node_id}: Config check failed - {str(config_err)[:100]}")
            
            if config_issues:
                error_msg = (
                    f"CRITICAL: Config issues detected after snapshot restore:\n"
                    + "\n".join(f"  - {issue}" for issue in config_issues) +
                    f"\n\nWithout correct static_genesis_event, genesis event won't load and UTXO won't be indexed!"
                )
                logger.error("config_issues_after_snapshot_restore",
                           issues=config_issues,
                           note=error_msg)
                # Don't fail here - continue to check logs and attempt transfer
            
            # Check node logs for genesis event loading/rejection
            logger.info("checking_node_logs_for_genesis_event_loading",
                       note="Checking node logs for genesis event acceptance/rejection messages")
            
            genesis_event_loaded = False
            genesis_event_rejected = False
            genesis_event_reject_reason = None
            
            try:
                import docker
                docker_client = docker.from_env()
                
                for root_node in root_nodes[:1]:  # Check first root node
                    container_name = f"{compose_manager.project_name}-node-{root_node.node_id}"
                    try:
                        container = docker_client.containers.get(container_name)
                        node_logs = container.logs(tail=10000).decode('utf-8', errors='ignore')
                        
                        # Search for genesis event messages
                        for line in node_logs.split('\n'):
                            line_lower = line.lower()
                            
                            # Check for genesis event acceptance
                            if 'genesis' in line_lower and 'event' in line_lower:
                                if 'accept' in line_lower or 'loaded' in line_lower or 'added' in line_lower:
                                    genesis_event_loaded = True
                                    logger.info("genesis_event_loaded_found_in_logs",
                                               node_id=root_node.node_id,
                                               line=line[:200])
                                elif 'reject' in line_lower or 'wrong' in line_lower or 'invalid' in line_lower:
                                    genesis_event_rejected = True
                                    genesis_event_reject_reason = line[:300]
                                    logger.error("genesis_event_rejected_found_in_logs",
                                               node_id=root_node.node_id,
                                               line=line[:300])
                            
                            # Check for zerochain loading errors
                            if 'zerochain' in line_lower and ('error' in line_lower or 'fail' in line_lower):
                                logger.warning("zerochain_error_in_logs",
                                             node_id=root_node.node_id,
                                             line=line[:300])
                            
                            # Check for ledger_items or HAL/HRL messages
                            if ('ledger' in line_lower or 'hal' in line_lower or 'hrl' in line_lower) and 'zerochain' in line_lower:
                                if '0 datums' in line_lower or 'empty' in line_lower:
                                    logger.warning("zerochain_ledger_empty_in_logs",
                                                 node_id=root_node.node_id,
                                                 line=line[:300])
                        
                        logger.info("node_logs_analysis_complete",
                                   node_id=root_node.node_id,
                                   genesis_event_loaded=genesis_event_loaded,
                                   genesis_event_rejected=genesis_event_rejected,
                                   note="Node logs analysis - check genesis event status")
                        
                    except docker.errors.NotFound:
                        logger.warning("container_not_found_for_logs",
                                     container_name=container_name,
                                     node_id=root_node.node_id)
                        
            except Exception as log_err:
                logger.warning("node_logs_check_exception",
                             error=str(log_err),
                             note="Exception during node logs check - proceeding anyway")
            
            # Fail-fast if genesis event was rejected
            if genesis_event_rejected:
                error_msg = (
                    f"CRITICAL: Genesis event was REJECTED after snapshot restore!\n"
                    f"Rejection reason: {genesis_event_reject_reason}\n"
                    f"Without genesis event, zerochain won't load and UTXO won't be indexed!\n"
                    f"Check if static_genesis_event hash matches the actual genesis event hash."
                )
                logger.error("genesis_event_rejected_fail_fast",
                           reject_reason=genesis_event_reject_reason,
                           note=error_msg)
                raise RuntimeError(error_msg)
            
            # Warn if genesis event not found in logs
            if not genesis_event_loaded:
                logger.warning("genesis_event_not_found_in_logs",
                             note="Genesis event loading messages not found in logs - event may not have loaded")
            
            # CRITICAL: Verify TCELL token exists on zerochain after snapshot restore
            # Token should be restored from snapshot, but may need time to load
            # CRITICAL: If zerochain has 0 events, genesis event is not loading - check genesis event loading!
            logger.info("verifying_tcell_token_on_zerochain_after_snapshot_restore",
                       note="TCELL token should exist on zerochain after snapshot restore")
            
            # CRITICAL DIAGNOSTIC: Check zerochain loading FIRST - if events=0, genesis event is not loading!
            logger.info("diagnostic_checking_zerochain_loading_after_snapshot_restore",
                       note="CRITICAL: Checking if zerochain is loading after snapshot restore - if events=0, genesis event issue!")
            
            # Check DAG events immediately to see if zerochain loaded
            exit_code_dag_check, stdout_dag_check, stderr_dag_check = self.genesis._exec_cli(
                first_root_node.node_id,
                f"dag event list -net {self.network_name} -chain zerochain -from events -limit 10",
                check_output=False
            )
            
            total_events_after_restore = 0
            if exit_code_dag_check == 0 and stdout_dag_check:
                total_match = re.search(r'total events:\s*(\d+)', stdout_dag_check, re.IGNORECASE)
                if total_match:
                    total_events_after_restore = int(total_match.group(1))
            
            logger.warning("zerochain_loading_diagnostic_after_snapshot_restore",
                         total_events=total_events_after_restore,
                         stdout_preview=stdout_dag_check[:500] if stdout_dag_check else "empty",
                         note=f"CRITICAL: Zerochain has {total_events_after_restore} events after snapshot restore. "
                              f"If 0, genesis event is NOT loading - check static_genesis_event configuration!")
            
            if total_events_after_restore == 0:
                # CRITICAL: Zerochain not loaded - genesis event is not loading
                # We already checked configs and logs above, so just fail fast here
                error_msg = (
                    f"CRITICAL: Zerochain has 0 events after snapshot restore! "
                    f"Genesis event is NOT loading. "
                    f"This means zerochain files are restored but genesis event is not being accepted. "
                    f"Check config_issues above and genesis_event_rejected status from logs analysis."
                )
                logger.error("zerochain_not_loaded_after_snapshot_restore",
                           total_events=total_events_after_restore,
                           config_issues=config_issues if config_issues else [],
                           genesis_event_rejected=genesis_event_rejected,
                           note=error_msg)
                raise RuntimeError(error_msg)
            
            # CRITICAL: Wait for TCELL token to be accessible on zerochain after snapshot restore
            # After snapshot restore, chains are loaded but token may not be immediately accessible
            # Token must be visible via token list or token show before we can transfer from emission
            logger.info("waiting_for_tcell_token_accessible_after_snapshot_restore")
            waiter_token = TokenInMempoolWaiter(
                exec_cli=self.genesis._exec_cli,
                node_id=first_root_node.node_id,
                network_name=self.network_name,
                token_name="TCELL",
                chain="zerochain",
                poll_interval=2.0
            )
            try:
                await waiter_token.wait(timeout=60.0)
            except TimeoutError:
                # Final diagnostic: collect all information
                logger.error("tcell_token_not_found_final_diagnostic",
                           note="Collecting final diagnostic information")
                
                # Try token list one more time with full output
                exit_code_final, stdout_final, stderr_final = self.genesis._exec_cli(
                    first_root_node.node_id,
                    f"token list -net {self.network_name} -chain zerochain",
                    check_output=False
                )
                
                logger.error("final_token_list_check",
                           exit_code=exit_code_final,
                           stdout=stdout_final[:1000] if stdout_final else "empty",
                           stderr=stderr_final[:500] if stderr_final else "empty")
                
                # Check zerochain DAG events
                exit_code_dag_final, stdout_dag_final, _ = self.genesis._exec_cli(
                    first_root_node.node_id,
                    f"dag event list -net {self.network_name} -chain zerochain -from events -limit 10",
                    check_output=False
                )
                
                logger.error("final_dag_events_check",
                           exit_code=exit_code_dag_final,
                           stdout=stdout_dag_final[:1000] if stdout_dag_final else "empty",
                           note="Check if zerochain has DAG events with token declaration")
                
                raise RuntimeError(
                    f"TCELL token not found on zerochain after 60.0s. "
                    f"Token should be restored from PHASE 1 snapshot. "
                    f"Cannot proceed with token transfers. "
                    f"Check if token was properly saved in snapshot or if zerochain is properly loaded. "
                    f"Final token list exit_code: {exit_code_final}, DAG events exit_code: {exit_code_dag_final}"
                )
            
            # Get fee_collector wallet address
            fee_collector_addr = await self.get_wallet_address(
                first_root_node.node_id,
                emission_wallet_name
            )
            logger.info("fee_collector_wallet_address", address=fee_collector_addr[:16])
            
            # CRITICAL: Check fee_collector wallet balance on zerochain (not main chain!)
            # Tokens were transferred to fee_collector wallet on zerochain in PHASE 1
            logger.info("checking_fee_collector_wallet_balance_on_zerochain",
                       wallet_name=emission_wallet_name,
                       wallet_addr=fee_collector_addr[:16],
                       chain="zerochain",
                       note="CRITICAL: Checking balance on zerochain, not main chain")
            
            import re
            import decimal
            
            fee_collector_balance_sufficient = False
            fee_collector_balance_datoshi = None
            
            try:
                # Check balance on zerochain
                exit_code, stdout, stderr = self.genesis._exec_cli(
                    first_root_node.node_id,
                    f"wallet info -w {emission_wallet_name} -net {self.network_name} -chain zerochain",
                    check_output=False
                )
                
                logger.info("fee_collector_wallet_info_on_zerochain",
                           exit_code=exit_code,
                           stdout_preview=stdout[:1000] if stdout else "empty",
                           stderr=stderr[:500] if stderr else "empty",
                           note="Full wallet info output for zerochain")
                
                if exit_code == 0 and stdout:
                    # Parse datoshi balance for precise comparison
                    datoshi_match = re.search(
                        r'datoshi["\']?\s*:\s*["\']?(\d+)',
                        stdout,
                        re.IGNORECASE
                    )
                    
                    if datoshi_match:
                        fee_collector_balance_datoshi = datoshi_match.group(1)
                        logger.info("fee_collector_balance_datoshi_found",
                                   wallet_name=emission_wallet_name,
                                   datoshi=fee_collector_balance_datoshi,
                                   chain="zerochain")
                        
                        # Check if balance is sufficient for transfer (120.0e+18 = 120000000000000000000 datoshi)
                        # Plus fee (0.1 TCELL = 100000000000000000 datoshi)
                        required_amount = decimal.Decimal("120.0e+18")  # 120 TCELL
                        required_fee = decimal.Decimal("0.1e+18")  # 0.1 TCELL
                        required_total = required_amount + required_fee
                        
                        try:
                            balance_decimal = decimal.Decimal(fee_collector_balance_datoshi)
                            if balance_decimal >= required_total:
                                fee_collector_balance_sufficient = True
                                logger.info("fee_collector_balance_sufficient",
                                           wallet_name=emission_wallet_name,
                                           balance_datoshi=fee_collector_balance_datoshi,
                                           required_total=str(required_total),
                                           chain="zerochain",
                                           note="Balance is sufficient for transfer")
                            else:
                                logger.error("fee_collector_balance_insufficient",
                                           wallet_name=emission_wallet_name,
                                           balance_datoshi=fee_collector_balance_datoshi,
                                           required_total=str(required_total),
                                           chain="zerochain",
                                           note="Balance is insufficient for transfer - this will cause transfer: False")
                        except Exception as parse_err:
                            logger.warning("failed_to_parse_balance_for_comparison",
                                         wallet_name=emission_wallet_name,
                                         datoshi=fee_collector_balance_datoshi,
                                         error=str(parse_err))
                    else:
                        logger.warning("fee_collector_datoshi_not_found_in_wallet_info",
                                     wallet_name=emission_wallet_name,
                                     output_preview=stdout[:1000],
                                     chain="zerochain",
                                     note="Cannot parse datoshi balance - may indicate wallet has no tokens on zerochain")
                    
                    # Also check if TCELL is mentioned at all
                    balance_found = "TCELL" in stdout or "tcell" in stdout.lower()
                    if balance_found:
                        logger.info("fee_collector_wallet_has_tcell_mentioned",
                                   wallet_name=emission_wallet_name,
                                   chain="zerochain",
                                   note="TCELL token is mentioned in wallet info")
                    else:
                        logger.warning("fee_collector_wallet_no_tcell_mentioned",
                                     wallet_name=emission_wallet_name,
                                     output_preview=stdout[:1000],
                                     chain="zerochain",
                                     note="TCELL token not mentioned in wallet info - may indicate zero balance")
                else:
                    logger.error("failed_to_get_wallet_info_on_zerochain",
                               exit_code=exit_code,
                               stderr=stderr[:500] if stderr else "empty",
                               wallet_name=emission_wallet_name,
                               chain="zerochain",
                               note="Failed to get wallet info - this will cause transfer: False")
                    
            except Exception as e:
                logger.error("wallet_info_check_exception_on_zerochain",
                           wallet_name=emission_wallet_name,
                           error=str(e),
                           chain="zerochain",
                           note="Exception while checking wallet balance - transfer will likely fail")
            
            # CRITICAL: Fail fast if balance is insufficient
            if not fee_collector_balance_sufficient:
                raise RuntimeError(
                    f"Fee_collector wallet balance on zerochain is insufficient for transfer. "
                    f"Wallet: {emission_wallet_name}, Address: {fee_collector_addr[:16]}, "
                    f"Balance datoshi: {fee_collector_balance_datoshi if fee_collector_balance_datoshi else 'unknown'}, "
                    f"Required: 120.0e+18 + 0.1e+18 = 120.1e+18 datoshi. "
                    f"This will cause 'transfer: False' error. "
                    f"Check if tokens were properly transferred to fee_collector wallet on zerochain in PHASE 1."
                )
            
            # CRITICAL DIAGNOSTIC: Check if transactions are loaded from chain files into ledger_items
            # After snapshot restore, transactions MUST be loaded from chain files via dap_chain_load_all
            # If transactions are not loaded, dap_ledger_get_list_tx_outs_unspent_by_addr will return empty
            # This causes "transfer: False" even if balance is visible (from balance_accounts cache)
            logger.info("diagnostic_checking_transactions_loaded_from_chain_files",
                       note="CRITICAL: Checking if zerochain transactions are loaded into ledger_items hash table")
            
            zerochain_events_loaded = False
            total_events_count = 0
            
            try:
                # Check if chain files exist and have events
                for node in root_nodes:
                    node_id = node.node_id
                    
                    # Check DAG events count on zerochain
                    dag_events_cmd = (
                        f"dag event list -net {self.network_name} -chain zerochain"
                    )
                    exit_code, stdout, stderr = self.genesis._exec_cli(
                        node_id, dag_events_cmd, check_output=False
                    )
                    
                    if exit_code == 0:
                        # Parse total events count
                        total_events_match = re.search(r'total events:\s*(\d+)', stdout, re.IGNORECASE)
                        if total_events_match:
                            total_events = int(total_events_match.group(1))
                            total_events_count = total_events  # Store for fail-fast check
                            logger.info("zerochain_events_count_check",
                                       node_id=node_id,
                                       total_events=total_events,
                                       note=f"Zerochain has {total_events} events in DAG")
                            
                            if total_events == 0:
                                logger.error("zerochain_has_zero_events_after_snapshot_restore",
                                           node_id=node_id,
                                           note="CRITICAL: Zerochain has 0 events - transactions are NOT loaded from chain files!")
                            elif total_events >= 3:
                                zerochain_events_loaded = True
                                logger.info("zerochain_events_loaded_from_chain_files",
                                           node_id=node_id,
                                           total_events=total_events,
                                           note="Zerochain events are loaded from chain files")
                                # Events are loaded, but transactions may still not be in ledger_items
                                # This happens if genesis event is rejected or events fail validation
                    else:
                        logger.warning("failed_to_check_dag_events",
                                     node_id=node_id,
                                     exit_code=exit_code,
                                     stderr=stderr[:500] if stderr else "empty")
            except Exception as chain_check_err:
                logger.warning("chain_files_check_exception",
                             error=str(chain_check_err),
                             note="Exception while checking chain files - proceeding anyway")
            
            # CRITICAL FAIL-FAST: If zerochain has 0 events after snapshot restore, transactions won't load
            # This means genesis event was rejected or chain files weren't loaded properly
            # Without events in DAG, transactions won't be indexed in ledger_items, causing "transfer: False"
            if total_events_count == 0:
                error_msg = (
                    f"CRITICAL: Zerochain has 0 events after snapshot restore! "
                    f"This means transactions are NOT loaded from chain files into ledger_items hash table. "
                    f"Without events in DAG, dap_ledger_get_list_tx_outs_unspent_by_addr will return empty, "
                    f"causing 'transfer: False' even if balance is visible. "
                    f"Check if genesis event hash matches static_genesis_event in zerochain.cfg, "
                    f"or if chain files were properly restored from snapshot."
                )
                logger.error("zerochain_events_not_loaded_fail_fast",
                           total_events=total_events_count,
                           note=error_msg)
                raise RuntimeError(error_msg)
            
            # CRITICAL: After snapshot restore, transactions may be in DAG events but not indexed in ledger
            # SDK's dap_ledger_get_list_tx_outs_with_val requires UTXO to be in ledger_items hash table
            # Balance is visible from balance_accounts (GDB cache), but UTXO must be in ledger_items (from chain files)
            
            # CRITICAL DIAGNOSTIC: Check if static_genesis_event is loaded correctly
            # If genesis event is not loaded, all subsequent events won't load either!
            logger.info("diagnostic_checking_genesis_event_loading",
                       wallet_name=emission_wallet_name,
                       wallet_addr=fee_collector_addr[:16],
                       chain="zerochain",
                       note="Checking if static_genesis_event is loaded - if not, all events won't load!")
            
            try:
                # Check zerochain config for static_genesis_event
                static_genesis_hash, is_static_genesis, seed_mode = await verify_zerochain_config(
                    base_path=self.genesis.base_path,
                    node_id=first_root_node.node_id,
                    network_name=self.network_name,
                    config_path=self.config_path
                )
                
                logger.info("zerochain_config_check",
                           static_genesis_hash=static_genesis_hash[:16] if static_genesis_hash else "NOT SET",
                           is_static_genesis_event=is_static_genesis,
                           seed_mode=seed_mode,
                           note="Zerochain config check - if static_genesis_event is set but seed_mode=false, genesis must match!")
                
                # Get actual genesis event from DAG
                # CRITICAL: We need to find event with event_number=1, not just the first in list
                # Events may be listed in different order, but genesis event always has event_number=1
                exit_code_genesis, stdout_genesis, stderr_genesis = self.genesis._exec_cli(
                    first_root_node.node_id,
                    f"dag event list -net {self.network_name} -chain zerochain -from events -limit 10",
                    check_output=False
                )
                
                actual_genesis_hash = None
                if exit_code_genesis == 0 and stdout_genesis:
                    # Find event with event_number=1 (genesis event)
                    # Format: "event number: 1\n                hash: 0x..."
                    genesis_match = re.search(r'event number:\s*1\s*\n\s*hash:\s*(0x[A-Fa-f0-9]{64})', stdout_genesis, re.MULTILINE)
                    if genesis_match:
                        actual_genesis_hash = genesis_match.group(1)
                    else:
                        # Fallback: if event_number=1 not found, try to find first event hash
                        # This may happen if genesis event was rejected
                        first_match = re.search(r'hash:\s*(0x[A-Fa-f0-9]{64})', stdout_genesis)
                        if first_match:
                            actual_genesis_hash = first_match.group(1)
                            logger.warning("genesis_event_not_found_by_number",
                                        first_event_hash=actual_genesis_hash[:16],
                                        note="Event number 1 not found - using first event in list. Genesis event may have been rejected!")
                
                logger.info("genesis_event_comparison",
                           static_genesis_hash=static_genesis_hash[:16] if static_genesis_hash else "NOT SET",
                           actual_genesis_hash=actual_genesis_hash[:16] if actual_genesis_hash else "NOT FOUND",
                           match=static_genesis_hash and actual_genesis_hash and static_genesis_hash.lower() == actual_genesis_hash.lower(),
                           note="CRITICAL: If hashes don't match, genesis event won't load and all events will be rejected!")
                
                if static_genesis_hash and actual_genesis_hash:
                    if static_genesis_hash.lower() != actual_genesis_hash.lower():
                        logger.error("genesis_event_mismatch",
                                   static_hash=static_genesis_hash[:16],
                                   actual_hash=actual_genesis_hash[:16],
                                   note="GENESIS EVENT MISMATCH! SDK will reject genesis event and all subsequent events won't load!")
                    else:
                        logger.info("genesis_event_match",
                                  hash=static_genesis_hash[:16],
                                  note="Genesis event matches - should load correctly")
                elif is_static_genesis and not static_genesis_hash:
                    logger.error("static_genesis_event_not_set",
                               note="is_static_genesis_event=true but static_genesis_event is not set in config!")
                elif is_static_genesis and not actual_genesis_hash:
                    logger.error("genesis_event_not_found_in_dag",
                               static_hash=static_genesis_hash[:16] if static_genesis_hash else "NOT SET",
                               note="Genesis event not found in DAG - chain may not have loaded!")
                
            except Exception as genesis_check_err:
                logger.warning("genesis_event_check_exception",
                             error=str(genesis_check_err),
                             note="Exception during genesis event check - proceeding anyway")
            
            # DIAGNOSTIC: Check node logs for zerochain loading issues
            logger.info("diagnostic_checking_node_logs_for_zerochain_loading",
                       wallet_name=emission_wallet_name,
                       wallet_addr=fee_collector_addr[:16],
                       chain="zerochain",
                       note="Checking node logs for zerochain loading messages")
            
            try:
                # Get logs from first root node using docker client
                import docker
                docker_client = docker.from_env()
                container_name = f"{compose_manager.project_name}-node-{first_root_node.node_id}"
                
                try:
                    container = docker_client.containers.get(container_name)
                    node_logs = container.logs(tail=5000).decode('utf-8', errors='ignore')
                except docker.errors.NotFound:
                    logger.warning("container_not_found_for_logs",
                                 container_name=container_name,
                                 note="Container not found - cannot get logs")
                    node_logs = ""
                
                # Search for zerochain loading messages
                zerochain_load_messages = []
                zerochain_loaded = False
                zerochain_load_errors = []
                genesis_event_messages = []
                
                for line in node_logs.split('\n'):
                    line_lower = line.lower()
                    if 'zerochain' in line_lower:
                        if 'load' in line_lower or 'loaded' in line_lower or 'loading' in line_lower:
                            zerochain_load_messages.append(line)
                            if 'loaded chain files' in line_lower:
                                zerochain_loaded = True
                        if 'error' in line_lower or 'fail' in line_lower or 'cannot' in line_lower:
                            zerochain_load_errors.append(line)
                    if 'genesis' in line_lower and ('event' in line_lower or 'accept' in line_lower or 'reject' in line_lower):
                        genesis_event_messages.append(line)
                
                logger.info("zerochain_load_analysis",
                           zerochain_load_messages_found=len(zerochain_load_messages),
                           zerochain_loaded=zerochain_loaded,
                           zerochain_load_errors_found=len(zerochain_load_errors),
                           genesis_event_messages_found=len(genesis_event_messages),
                           sample_messages=zerochain_load_messages[:10] if zerochain_load_messages else [],
                           sample_errors=zerochain_load_errors[:10] if zerochain_load_errors else [],
                           sample_genesis_messages=genesis_event_messages[:10] if genesis_event_messages else [],
                           note="Zerochain loading analysis from node logs - check genesis event messages!")
                
                if zerochain_load_errors:
                    logger.warning("zerochain_load_errors_detected",
                                 errors=zerochain_load_errors[:10],
                                 note="Zerochain loading errors detected - this may explain why events are not loading")
                
                if genesis_event_messages:
                    logger.warning("genesis_event_messages_detected",
                                 messages=genesis_event_messages[:10],
                                 note="Genesis event messages detected - check if event is being rejected")
                
            except Exception as log_err:
                logger.warning("node_logs_check_exception",
                             error=str(log_err),
                             note="Exception during node logs check - proceeding anyway")
            
            # DIAGNOSTIC: Check DAG events count vs ledger transactions
            logger.info("diagnostic_checking_dag_events_vs_ledger",
                       wallet_name=emission_wallet_name,
                       wallet_addr=fee_collector_addr[:16],
                       chain="zerochain",
                       note="Checking DAG events count - transactions should be in ledger_items")
            
            try:
                # Get DAG events count for zerochain
                exit_code_events, stdout_events, stderr_events = self.genesis._exec_cli(
                    first_root_node.node_id,
                    f"dag event list -net {self.network_name} -chain zerochain -from events",
                    check_output=False
                )
                
                dag_events_count = 0
                if exit_code_events == 0 and stdout_events:
                    # Count events in output (simple line count approximation)
                    dag_events_count = len([l for l in stdout_events.split('\n') if l.strip() and 'hash' in l.lower()])
                    logger.info("dag_events_count_found",
                               dag_events_count=dag_events_count,
                               stdout_preview=stdout_events[:500] if stdout_events else "empty",
                               note="DAG events found on zerochain")
                else:
                    logger.warning("dag_events_check_failed",
                                 exit_code=exit_code_events,
                                 stderr=stderr_events[:500] if stderr_events else "empty",
                                 note="Failed to get DAG events count")
                
                # Check if emission transaction is in ledger using ledger info (more reliable than tx_history)
                # tx_history depends on PVT(a_dag)->datums which may not be populated after snapshot restore
                # ledger info checks ledger_items directly, which is populated during chain loading
                emission_in_ledger = False
                if hasattr(self, 'emission_hash') and self.emission_hash:
                    try:
                        checker = LedgerTransactionChecker(
                            self.genesis._exec_cli,
                            first_root_node.node_id,
                            self.emission_hash,
                            network=self.network_name
                        )
                        emission_in_ledger = await checker.check()
                        logger.info("emission_transaction_ledger_check",
                                   emission_hash=self.emission_hash[:16],
                                   found_in_ledger=emission_in_ledger,
                                   note="Emission transaction check via ledger info (checks ledger_items directly)")
                    except Exception as ledger_check_err:
                        logger.warning("emission_ledger_check_exception",
                                     emission_hash=self.emission_hash[:16] if hasattr(self, 'emission_hash') and self.emission_hash else "unknown",
                                     error=str(ledger_check_err)[:200],
                                     note="Exception during emission ledger check")
                
                # DIAGNOSTIC: Also check tx_history for comparison (may be empty if PVT(a_dag)->datums is not populated)
                exit_code_txhist, stdout_txhist, stderr_txhist = self.genesis._exec_cli(
                    first_root_node.node_id,
                    f"tx_history -w {emission_wallet_name} -net {self.network_name} -chain zerochain -head",
                    check_output=False
                )
                
                tx_history_count = 0
                if exit_code_txhist == 0 and stdout_txhist:
                    # Try to extract total_tx_count from JSON output
                    tx_count_match = re.search(r'total_tx_count["\']?\s*:\s*(\d+)', stdout_txhist, re.IGNORECASE)
                    if tx_count_match:
                        tx_history_count = int(tx_count_match.group(1))
                    logger.info("tx_history_check_result_diagnostic",
                               tx_history_count=tx_history_count,
                               stdout_preview=stdout_txhist[:500] if stdout_txhist else "empty",
                               note="TX history count (diagnostic - may be empty if PVT(a_dag)->datums not populated)")
                else:
                    logger.warning("tx_history_check_failed_diagnostic",
                                 exit_code=exit_code_txhist,
                                 stderr=stderr_txhist[:500] if stderr_txhist else "empty",
                                 note="Failed to get tx_history (diagnostic - not critical)")
                
                # DIAGNOSTIC SUMMARY
                logger.warning("diagnostic_summary_balance_vs_utxo",
                             balance_datoshi=fee_collector_balance_datoshi,
                             dag_events_count=dag_events_count,
                             emission_in_ledger=emission_in_ledger,
                             tx_history_count=tx_history_count,
                             note=f"BALANCE VISIBLE: {fee_collector_balance_datoshi} datoshi, "
                                  f"DAG EVENTS: {dag_events_count}, "
                                  f"EMISSION IN LEDGER (via ledger info): {emission_in_ledger}, "
                                  f"TX HISTORY (diagnostic): {tx_history_count}. "
                                  f"ledger info checks ledger_items directly (reliable), "
                                  f"tx_history depends on PVT(a_dag)->datums (may be empty after snapshot restore)")
                
            except Exception as diag_err:
                logger.warning("diagnostic_check_exception",
                             error=str(diag_err),
                             note="Exception during diagnostic check - proceeding anyway")
            
            # CRITICAL: After snapshot restore, restart root nodes to trigger NET_STATE_LOADING
            # This ensures UTXO are indexed in ledger_items during node startup
            # SDK indexes UTXO only when in NET_STATE_LOADING or NET_STATE_SYNC_CHAINS
            logger.info("restarting_root_nodes_after_snapshot_restore_for_utxo_indexation",
                       note="CRITICAL: Restarting root nodes after snapshot restore to trigger NET_STATE_LOADING for UTXO indexation")
            
            root_services = [f"node-{n.node_id}" for n in root_nodes]
            
            # Gracefully stop root nodes using docker client directly
            logger.info("stopping_root_nodes_for_restart",
                       services=root_services,
                       note="Stopping root nodes before restart")
            
            # Stop containers using docker client
            for root_node in root_nodes:
                container_name = f"{compose_manager.project_name}-node-{root_node.node_id}"
                try:
                    container = self.docker_client.containers.get(container_name)
                    container.stop(timeout=30)
                    logger.debug("root_node_stopped", node_id=root_node.node_id)
                except Exception as e:
                    logger.warning("failed_to_stop_root_node",
                                 node_id=root_node.node_id,
                                 error=str(e)[:100])
            
            await asyncio.sleep(3.0)  # Wait for containers to stop
            
            # Restart root nodes - they will load in NET_STATE_LOADING and index UTXO
            logger.info("restarting_root_nodes",
                       services=root_services,
                       note="Restarting root nodes - SDK will load in NET_STATE_LOADING and index UTXO")
            compose_manager.up(services=root_services, detach=True, wait=False)
            
            # Wait for nodes to be online
            from ..monitoring.waiters import NetworkOnlineWaiter
            for root_node in root_nodes:
                waiter_online = NetworkOnlineWaiter(
                    exec_cli=self.genesis._exec_cli,
                    node_id=root_node.node_id,
                    network=self.network_name,
                    poll_interval=1.0
                )
                await waiter_online.wait(timeout=60.0)
            
            logger.info("root_nodes_restarted_online",
                       note="Root nodes restarted and online - UTXO should be indexed in ledger_items")
            
            # CRITICAL: Force network into NET_STATE_SYNC_CHAINS immediately after restart
            # SDK indexes UTXO only when in NET_STATE_LOADING or NET_STATE_SYNC_CHAINS
            # After restart, network may be in NET_STATE_ONLINE, so we need to force sync
            logger.info("forcing_network_sync_chains_immediately_after_restart",
                       note="CRITICAL: Forcing network into NET_STATE_SYNC_CHAINS immediately after restart to index UTXO")
            
            try:
                # Go offline first to reset network state
                exit_code_offline, stdout_offline, stderr_offline = self.genesis._exec_cli(
                    first_root_node.node_id,
                    f"net -net {self.network_name} go offline",
                    check_output=False
                )
                if exit_code_offline == 0:
                    logger.debug("network_offline_before_sync_after_restart",
                               note="Network is offline, proceeding to sync chains")
                    await asyncio.sleep(2.0)  # Wait for network to go offline
                else:
                    logger.warning("failed_to_go_offline_after_restart",
                                exit_code=exit_code_offline,
                                stderr=stderr_offline[:200] if stderr_offline else "empty",
                                note="Failed to go offline - proceeding anyway")
                
                # Force sync - this will reload events from chain files and index UTXO
                exit_code_sync, stdout_sync, stderr_sync = self.genesis._exec_cli(
                    first_root_node.node_id,
                    f"net -net {self.network_name} go sync",
                    check_output=False
                )
                if exit_code_sync == 0:
                    logger.info("network_sync_forced_after_restart",
                              stdout_preview=stdout_sync[:300] if stdout_sync else "empty",
                              note="Network sync forced - SDK should reload events and index UTXO")
                    
                    # Wait for sync to complete using NetworkSyncCompletionWaiter
                    from ..monitoring.waiters import NetworkSyncCompletionWaiter
                    sync_waiter = NetworkSyncCompletionWaiter(
                        exec_cli=self.genesis._exec_cli,
                        node_id=first_root_node.node_id,
                        network=self.network_name,
                        poll_interval=1.0
                    )
                    await sync_waiter.wait(timeout=120.0, name="network_sync_after_restart")
                    logger.info("network_sync_completed_after_restart",
                              note="Network sync completed - UTXO should be indexed in ledger_items")
                else:
                    logger.warning("failed_to_sync_after_restart",
                                 exit_code=exit_code_sync,
                                 stderr=stderr_sync[:200] if stderr_sync else "empty",
                                 note="Failed to sync - proceeding anyway")
            except Exception as sync_err:
                logger.warning("network_sync_exception_after_restart",
                             error=str(sync_err)[:200],
                             note="Exception during network sync after restart - proceeding anyway")
            
            # CRITICAL: After restart, trigger mempool_proc for all zerochain events to index UTXO
            # After snapshot restore, events may be in DAG but not in ledger_items
            # mempool_proc processes events from DAG into ledger_items
            logger.info("triggering_mempool_proc_for_all_zerochain_events_after_restart",
                       note="CRITICAL: Processing all zerochain events via mempool_proc to index UTXO in ledger_items")
            
            try:
                # Get all zerochain events
                exit_code_events, stdout_events, stderr_events = self.genesis._exec_cli(
                    first_root_node.node_id,
                    f"dag event list -net {self.network_name} -chain zerochain -from events -limit 10",
                    check_output=False
                )
                
                if exit_code_events == 0 and stdout_events:
                    # Extract event hashes from output
                    event_hashes = re.findall(r'hash:\s*(0x[A-Fa-f0-9]{64})', stdout_events, re.IGNORECASE)
                    
                    if event_hashes:
                        logger.info("found_zerochain_events_for_mempool_proc",
                                   event_count=len(event_hashes),
                                   note="Processing zerochain events via mempool_proc to index UTXO")
                        
                        # Process each event on all root nodes
                        for event_hash in event_hashes:
                            for root_node in root_nodes:
                                try:
                                    exit_code_mp, stdout_mp, stderr_mp = self.genesis._exec_cli(
                                        root_node.node_id,
                                        f"mempool_proc -datum {event_hash} -net {self.network_name} -chain zerochain",
                                        check_output=False
                                    )
                                    
                                    if exit_code_mp == 0:
                                        logger.debug("mempool_proc_success_for_event",
                                                   node_id=root_node.node_id,
                                                   event_hash=event_hash[:16],
                                                   note="Event processed via mempool_proc")
                                    else:
                                        logger.debug("mempool_proc_failed_for_event",
                                                   node_id=root_node.node_id,
                                                   event_hash=event_hash[:16],
                                                   exit_code=exit_code_mp,
                                                   stdout=stdout_mp[:200] if stdout_mp else "empty",
                                                   note="mempool_proc failed (may be already processed)")
                                except Exception as mp_err:
                                    logger.debug("mempool_proc_exception",
                                               node_id=root_node.node_id,
                                               event_hash=event_hash[:16],
                                               error=str(mp_err)[:100])
                        
                        logger.info("mempool_proc_completed_for_all_events",
                                   event_count=len(event_hashes),
                                   note="All zerochain events processed via mempool_proc - UTXO should be indexed")
                    else:
                        logger.warning("no_zerochain_events_found_for_mempool_proc",
                                     note="No zerochain events found - cannot process via mempool_proc")
                else:
                    logger.warning("failed_to_get_zerochain_events",
                                 exit_code=exit_code_events,
                                 stderr=stderr_events[:200] if stderr_events else "empty",
                                 note="Failed to get zerochain events for mempool_proc")
            except Exception as mp_err:
                logger.warning("mempool_proc_exception",
                             error=str(mp_err)[:200],
                             note="Exception during mempool_proc - proceeding anyway")
            
            # CRITICAL: Force network into NET_STATE_SYNC_CHAINS to enable UTXO indexation
            # After snapshot restore, SDK may not be in NET_STATE_LOADING, so UTXO won't be indexed
            # By forcing sync chains, we ensure UTXO are indexed in ledger_items
            logger.info("forcing_network_sync_chains_for_utxo_indexation",
                       wallet_name=emission_wallet_name,
                       wallet_addr=fee_collector_addr[:16],
                       chain="zerochain",
                       note="CRITICAL: Forcing network into NET_STATE_SYNC_CHAINS to enable UTXO indexation after snapshot restore")
            
            try:
                # Step 1: Go offline first to reset state
                logger.info("going_offline_before_sync_chains",
                           node_id=first_root_node.node_id,
                           note="Going offline to reset network state before sync")
                exit_code_offline, stdout_offline, stderr_offline = self.genesis._exec_cli(
                    first_root_node.node_id,
                    f"net -net {self.network_name} go offline",
                    check_output=False
                )
                
                if exit_code_offline == 0:
                    await asyncio.sleep(2.0)  # Wait for offline state
                    logger.info("network_offline_before_sync",
                               note="Network is offline, proceeding to sync chains")
                else:
                    logger.warning("failed_to_go_offline",
                                 exit_code=exit_code_offline,
                                 stderr=stderr_offline[:500] if stderr_offline else "empty",
                                 note="Failed to go offline, proceeding anyway")
                
                # Step 2: Force sync chains - this should trigger UTXO indexation
                # net go sync forces network into NET_STATE_SYNC_CHAINS state
                exit_code_sync, stdout_sync, stderr_sync = self.genesis._exec_cli(
                    first_root_node.node_id,
                    f"net -net {self.network_name} go sync",
                    check_output=False
                )
                
                logger.info("net_sync_chains_result",
                           exit_code=exit_code_sync,
                           stdout_preview=stdout_sync[:1000] if stdout_sync else "empty",
                           stderr=stderr_sync[:500] if stderr_sync else "empty",
                           note="Net sync chains result - should reload zerochain transactions into ledger")
                
                if exit_code_sync == 0:
                    # Wait for sync to complete using NetworkSyncCompletionWaiter
                    from ..monitoring.waiters import NetworkSyncCompletionWaiter
                    sync_waiter = NetworkSyncCompletionWaiter(
                        exec_cli=self.genesis._exec_cli,
                        node_id=first_root_node.node_id,
                        network=self.network_name,
                        poll_interval=1.0
                    )
                    await sync_waiter.wait(timeout=120.0, name="network_sync_for_utxo_indexation")
                    logger.info("network_sync_completed_for_utxo_indexation",
                              note="Network sync completed - UTXO should be indexed in ledger_items")
                    
                    # Check network state
                    exit_code_state, stdout_state, stderr_state = self.genesis._exec_cli(
                        first_root_node.node_id,
                        f"net -net {self.network_name} get status",
                        check_output=False
                    )
                    
                    if exit_code_state == 0 and stdout_state:
                        logger.info("network_state_after_sync",
                                   state_output=stdout_state[:500],
                                   note="Network state after sync command")
                    
                    # CRITICAL: Wait for UTXO to be indexed in ledger_items before proceeding
                    # After net go sync, we need to wait for transactions to be loaded into ledger_items
                    # This is required for transfer_tokens to work - it uses dap_ledger_get_list_tx_outs_unspent_by_addr
                    logger.info("waiting_for_utxo_indexation_after_sync",
                               wallet_addr=fee_collector_addr[:16],
                               note="CRITICAL: Waiting for UTXO to be indexed in ledger_items after sync")
                    
                    waiter_utxo = UTXOIndexationWaiter(
                        exec_cli=self.genesis._exec_cli,
                        node_id=first_root_node.node_id,
                        wallet_addr=fee_collector_addr,
                        network=self.network_name,
                        chain="zerochain",
                        poll_interval=2.0
                    )
                    
                    try:
                        await waiter_utxo.wait(timeout=60.0, name="utxo_indexation_after_sync")
                        logger.info("utxo_indexed_after_sync",
                                   wallet_addr=fee_collector_addr[:16],
                                   note="UTXO indexed in ledger_items - transfer should now work")
                    except TimeoutError:
                        # Re-check tx_history for diagnostic
                        # WORKAROUND: Use -head flag to force forward iteration (get_first/get_next)
                        # because DAG chains don't implement get_last/get_prev callbacks
                        exit_code_txhist2, stdout_txhist2, stderr_txhist2 = self.genesis._exec_cli(
                            first_root_node.node_id,
                            f"tx_history -w {emission_wallet_name} -net {self.network_name} -chain zerochain -head",
                            check_output=False
                        )
                        
                        tx_history_count_after = 0
                        if exit_code_txhist2 == 0 and stdout_txhist2:
                            tx_count_match = re.search(r'total_tx_count["\']?\s*:\s*(\d+)', stdout_txhist2, re.IGNORECASE)
                            if tx_count_match:
                                tx_history_count_after = int(tx_count_match.group(1))
                        
                        error_msg = (
                            f"CRITICAL: UTXO not indexed after sync! "
                            f"tx_history_count before: {tx_history_count}, after: {tx_history_count_after}. "
                            f"Without UTXO indexed in ledger_items, transfer will fail with 'transfer: False'. "
                            f"Check if zerochain events are loaded and if network is in NET_STATE_SYNC_CHAINS."
                        )
                        logger.error("utxo_not_indexed_after_sync",
                                   tx_history_before=tx_history_count,
                                   tx_history_after=tx_history_count_after,
                                   wallet_addr=fee_collector_addr[:16],
                                   note=error_msg)
                        raise RuntimeError(error_msg)
                else:
                    logger.warning("net_sync_chains_failed",
                                 exit_code=exit_code_sync,
                                 stderr=stderr_sync[:500] if stderr_sync else "empty",
                                 note="Net sync chains failed - UTXO may not be indexed")
            except Exception as sync_err:
                logger.warning("zerochain_sync_exception",
                             error=str(sync_err),
                             note="Exception during zerochain sync - proceeding anyway")
            
            # CRITICAL: NOW creating transfers to master wallets in PHASE 2!
            # REASON: Moved from PHASE 1 because UTXO indexation issue after hard restart
            # In PHASE 2 after snapshot restore, SDK is in load_mode and UTXO should be indexed
            logger.info("creating_transfers_to_master_wallets_in_phase2",
                       wallet_name=emission_wallet_name,
                       wallet_addr=fee_collector_addr[:16],
                       master_count=len(master_nodes),
                       note="Creating transfers from fee_collector to master wallets in PHASE 2.")
            
            # Amount to transfer per master node
            transfer_amount = "120.0e+18"  # 100 for staking + 20 for operations
            
            for master_node in master_nodes:
                wallet_addr = master_wallets[master_node.node_id]
                master_idx = master_node.node_id - 4
                wallet_name = f"{self.network_name}_master_{master_idx}"
                
                logger.info("creating_transfer_to_master_in_phase2",
                           node_id=master_node.node_id,
                           from_wallet="fee_collector",
                           to_wallet=wallet_name,
                           amount=transfer_amount)
                
                # Transfer from fee_collector wallet on zerochain
                # CRITICAL: Fail-fast on transfer errors - if UTXO are not indexed, test must fail immediately
                # DO NOT catch exceptions here - let RuntimeError propagate to stop test execution
                tx_hash = await self.genesis.transfer_tokens(
                    from_node_id=first_root_node.node_id,
                    from_wallet="fee_collector",
                    to_address=wallet_addr,
                    amount=transfer_amount,
                    fee="0.1",
                    chain="zerochain"
                )
                
                logger.info("transfer_to_master_created_in_phase2",
                           node_id=master_node.node_id,
                           tx_hash=tx_hash[:16],
                           to_wallet=wallet_name,
                           amount=transfer_amount)
                
                # Process transfer through DAG-PoA
                await self.genesis.sync_mgr.process_zerochain_datum(tx_hash, root_nodes)
                
                logger.info("transfer_to_master_finalized_in_phase2",
                           node_id=master_node.node_id,
                           tx_hash=tx_hash[:16])
            
            logger.info("all_master_transfers_created_in_phase2",
                       master_count=len(master_nodes),
                       note="All transfers to master wallets created in PHASE 2")
                
            # Step 7: Delegate keys via srv_stake on zerochain
            # This creates delegation WITHOUT orders - directly through transaction on zerochain
            logger.info("delegating_keys_via_stake_for_all_master_nodes_on_zerochain")
            
            for master_node in master_nodes:
                validator_idx = master_node.node_id - 4
                cert_name = f"pvt.{self.network_name}.master.{validator_idx}"
                wallet_name = f"{self.network_name}_master_{validator_idx}"
                
                # Delegate key with stake amount
                stake_amount = "100.0e+18"  # 100 tokens stake (out of 120 transferred)
                
                tx_hash = await self.delegate_key_via_stake(
                    node_id=master_node.node_id,
                    wallet_name=wallet_name,
                    amount=stake_amount,
                    cert_name=cert_name,
                    chain="zerochain"  # Delegation on zerochain
                )
                logger.info("key_delegated_for_master_node_on_zerochain",
                           node_id=master_node.node_id,
                           cert_name=cert_name,
                           stake_amount=stake_amount,
                           tx_hash=tx_hash[:16] if tx_hash else "unknown")
                
                # Wait for delegation transaction to be processed
                if tx_hash:
                    waiter_tx = TransactionProcessedWaiter(
                        exec_cli=self.genesis._exec_cli,
                        node_id=master_node.node_id,
                        tx_hash=tx_hash,
                        network_name=self.network_name,
                        chain="zerochain",
                        poll_interval=1.0
                    )
                    await waiter_tx.wait(timeout=30.0)
            
            # Step 8: GDB sync and wait for delegation transactions
            logger.info("triggering_gdb_sync_for_zerochain_delegations")
            await self.genesis.validator_mgr.sync_orders_across_network(all_validator_nodes)
            waiter_gdb_sync2 = GDBSyncCompleteWaiter(
                exec_cli=self.genesis._exec_cli,
                nodes=all_validator_nodes,
                network_name=self.network_name,
                poll_interval=2.0
            )
            await waiter_gdb_sync2.wait(timeout=30.0)
            
            
            # Step 11: Verify delegations are visible (check stake service)
            logger.info("verifying_key_delegations_synced")
            # Wait for delegations to sync across network via GDB
            waiter_delegations = DelegationsSyncedWaiter(
                exec_cli=self.genesis._exec_cli,
                nodes=master_nodes,
                expected_count=len(master_nodes),
                network_name=self.network_name,
                poll_interval=2.0
            )
            await waiter_delegations.wait(timeout=60.0)
            logger.info("delegations_confirmed_synced")
            
            # CRITICAL: Flush GDB to disk before restart
            # This ensures delegations are written to MDBX files
            logger.info("flushing_gdb_to_disk_before_restart")
            for master_node in master_nodes:
                try:
                    exit_code, stdout, stderr = self.genesis._exec_cli(
                        master_node.node_id,
                        "global_db flush",
                        check_output=False
                    )
                    if exit_code == 0:
                        logger.debug("gdb_flushed_to_disk",
                                   node_id=master_node.node_id,
                                   output=stdout[:200] if stdout else "")
                    else:
                        logger.warning("gdb_flush_failed",
                                     node_id=master_node.node_id,
                                     exit_code=exit_code,
                                     stderr=stderr[:200] if stderr else "")
                except Exception as e:
                    logger.warning("gdb_flush_exception",
                                 node_id=master_node.node_id,
                                 error=str(e))
            logger.info("gdb_flushed_on_all_nodes")
            
            # Step 12: Restart master nodes to reload chains with delegations
            # At this point, order should be in GDB cluster, so after restart
            # when chains load and ESBocs initializes, order should be found
            logger.info("gracefully_restarting_master_nodes_to_reload_chains_with_order")
            compose_manager.restart(services=master_services)
            waiter_containers2 = MasterContainersRunningWaiter(
                docker_client=self.docker_client,
                master_nodes=master_nodes,
                poll_interval=1.0
            )
            await waiter_containers2.wait(timeout=60.0)
            # Wait for CLI to be ready after restart
            for master_node in master_nodes:
                waiter_cli2 = CLIReadyWaiter(
                    exec_cli=self.genesis._exec_cli,
                    node_id=master_node.node_id,
                    network_name=self.network_name,
                    poll_interval=0.5
                )
                await waiter_cli2.wait(timeout=30.0)
            logger.info("cli_servers_ready_after_restart")
            
            # Step 13: GDB sync after restart to ensure delegations are loaded
            logger.info("triggering_gdb_sync_immediately_after_restart")
            await self.genesis.validator_mgr.sync_orders_across_network(master_nodes)
            
            # Step 14: CRITICAL - Wait for stake service to be ready with delegated keys
            # After restart, stake service needs time to:
            # 1. Load delegations from GDB (srv_stake delegate transactions on zerochain)
            # 2. Mark validators as active
            # 3. Make validators available for ESBocs consensus (s_get_validators_list)
            logger.info("waiting_for_stake_service_ready_with_delegations")
            waiter_stake = StakeServiceReadyWaiter(
                exec_cli=self.genesis._exec_cli,
                nodes=master_nodes,
                network_name=self.network_name,
                poll_interval=2.0
            )
            await waiter_stake.wait(timeout=60.0)
            logger.info("stake_service_ready_with_delegations")
            
            # Step 15: Verify delegated keys are active in stake service
            logger.info("verifying_delegated_keys_active_in_stake_service")
            # Check that stake service has delegated keys loaded
            for master_node in master_nodes:
                try:
                    exit_code, stdout, stderr = self.genesis._exec_cli(
                        master_node.node_id,
                        f"srv_stake list keys -net {self.network_name}",
                        check_output=False
                    )
                    if exit_code == 0 and stdout and len(stdout.strip()) > 50:
                        logger.info("stake_service_has_delegated_keys",
                                   node_id=master_node.node_id,
                                   output_preview=stdout[:200])
                    else:
                        logger.warning("stake_service_no_delegated_keys",
                                     node_id=master_node.node_id,
                                     exit_code=exit_code,
                                     output=stdout[:200] if stdout else "empty")
                except Exception as e:
                    logger.warning("stake_service_check_failed",
                                 node_id=master_node.node_id,
                                 error=str(e)[:100])
            
            # Step 13: Wait for network consensus
            logger.info("waiting_for_root_and_master_consensus")
            all_validator_nodes_dict = {f"node{n.node_id}": n for n in all_validator_nodes}
            from ..monitoring.network_consensus import NetworkConsensusMonitor
            consensus_monitor_all = NetworkConsensusMonitor(
                nodes=all_validator_nodes_dict,
                node_cli_path="cellframe-node-cli",
                network_name=self.network_name
            )
            
            await consensus_monitor_all.wait_for_network_ready(timeout=120.0)
            
            # Step 16: Wait for ESBocs consensus to become active
            # Now ALL master nodes participate (not just first)
            logger.info("waiting_for_esbocs_consensus_to_become_active_all_masters")
            
            # Factory function for creating StakeServiceReadyWaiter
            def create_stake_service_waiter():
                return StakeServiceReadyWaiter(
                    exec_cli=self.genesis._exec_cli,
                    nodes=master_nodes,
                    network_name=self.network_name,
                    poll_interval=2.0
                )
            
            waiter_esbocs = ESBocsConsensusActiveWaiter(
                exec_cli=self.genesis._exec_cli,
                nodes=master_nodes,
                network_name=self.network_name,
                poll_interval=3.0,
                stake_service_waiter_factory=create_stake_service_waiter
            )
            await waiter_esbocs.wait(timeout=90.0)
            logger.info("esbocs_consensus_active_all_masters")
            
            # Step 17: Create first transaction → genesis block
            # Now can be created by ANY master node (all have delegated keys)
            logger.info("creating_first_transaction_main_chain")
            tx_hash = await self.genesis.token_mgr.create_first_transaction(
                emission_hash, 
                master_nodes=master_nodes  # Any master node can create transaction
            )
            logger.info("first_transaction_created", hash=tx_hash[:16])
            
            # Step 18: Wait for genesis block
            logger.info("waiting_for_main_genesis_block_creation")
            waiter_block = FirstBlockWaiter(
                exec_cli=self.genesis._exec_cli,
                network_name=self.network_name,
                chain_name="main",
                master_nodes=master_nodes,
                poll_interval=3.0
            )
            await waiter_block.wait(timeout=60.0)
            logger.info("main_genesis_block_created")
            
            # Step 17: Get genesis block hash
            main_genesis_hash = await self.genesis.config_mgr.get_genesis_block_hash("main")
            if not main_genesis_hash:
                raise RuntimeError("Failed to retrieve main genesis block hash")
            logger.info("main_genesis_block_hash", hash=main_genesis_hash[:16])
            
            # Step 18: Update static_genesis_block in ALL configs
            logger.info("updating_static_genesis_block_in_all_configs")
            await self.genesis.config_mgr.update_static_genesis_in_config(
                "main", 
                main_genesis_hash, 
                node_configs
            )
            logger.info("static_genesis_updated")
            
            # Step 19: Disable seed_mode and genesis_mode in ALL validator configs
            logger.info("disabling_seed_mode_for_all_validators")
            root_node_ids = [n.node_id for n in root_nodes]
            master_node_ids = [n.node_id for n in master_nodes]
            self.genesis.config_mgr.disable_seed_mode_in_configs(root_node_ids + master_node_ids)
            logger.info("disabling_genesis_mode_for_all_validators")
            self.genesis.config_mgr.disable_genesis_mode_in_chain_configs(
                "main", 
                root_node_ids + master_node_ids
            )
            
            # Step 20: Sequential hard restart
            logger.info("sequential_hard_restart_all_validators")
            service_groups = [
                [f"node-{root_node_ids[0]}"],
                [f"node-{root_node_ids[1]}"],
                [f"node-{root_node_ids[2]}"],
                master_services
            ]
            
            await lifecycle_manager.sequential_restart_with_config_reload(
                service_groups=service_groups,
                compose_manager=compose_manager,
                state_manager=state_manager,
                flush_timeout=60,
                startup_timeout=60,
                inter_group_delay=5.0
            )
            
            # Step 21: Wait for validators to come back online
            logger.info("waiting_for_all_validators_after_hard_restart")
            await consensus_monitor_all.wait_for_links_connecting_state(timeout=60.0)
            logger.info("all_validators_restarted_with_genesis_block_config")
            
            # Step 22: Soft reconnect
            logger.info("soft_reconnect_after_hard_restart")
            await self.genesis.registration_mgr.soft_network_reconnect(
                all_validator_nodes, 
                wait_for_links=True
            )
            logger.info("full_mesh_connectivity_established")
            
            logger.info("esbocs_genesis_complete_with_pos_stake_delegation")
            
        except Exception as e:
            logger.error("esbocs_genesis_failed", error=str(e))
            raise RuntimeError(f"ESBocs genesis failed: {e}") from e
    

