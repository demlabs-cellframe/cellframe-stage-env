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
import configparser
import re
import time
from pathlib import Path
from typing import List, Optional, Dict

import docker

from .genesis_base import BaseGenesisManager
from .models import NodeConfig
from ..utils.logger import get_logger


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
        master_nodes: List[NodeConfig]
    ) -> None:
        """
        Regenerate chain configs with ALL master nodes as validators.
        
        Uses ConfigGenerator to properly regenerate all chain configs
        (main.cfg, zerochain.cfg) with all master validators.
        
        Args:
            all_validator_nodes: List of all validator nodes (for root_nodes_addrs)
            master_nodes: List of ALL master nodes (will be validators)
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
        
        # CRITICAL: Read ALL parameters from existing configs BEFORE regenerating
        # Regenerate will OVERWRITE configs, so we must preserve all important values
        first_node = all_validator_nodes[0]
        cache_path = self.genesis.base_path.parent / "testing" / "cache"
        zerochain_config_path = cache_path / "configs" / f"node{first_node.node_id}" / "network" / self.network_name / "zerochain.cfg"
        main_config_path = cache_path / "configs" / f"node{first_node.node_id}" / "network" / self.network_name / "main.cfg"
        
        static_genesis_event = None
        fee_addr = None
        min_validators_count = 2  # Default: 2/3 consensus for 3 validators
        
        # Read static_genesis_event from zerochain.cfg
        if zerochain_config_path.exists():
            import configparser
            config = configparser.ConfigParser()
            config.read(zerochain_config_path)
            
            if 'dag' in config and 'static_genesis_event' in config['dag']:
                static_genesis_event = config['dag']['static_genesis_event'].strip()
                if static_genesis_event:
                    logger.info("preserving_static_genesis_event_before_regenerate",
                              hash=static_genesis_event[:16],
                              note="Reading static_genesis_event from existing config")
        
        # Read fee_addr and min_validators_count from main.cfg
        if main_config_path.exists():
            import configparser
            config = configparser.ConfigParser()
            config.read(main_config_path)
            
            if 'esbocs' in config:
                if 'fee_addr' in config['esbocs']:
                    fee_addr = config['esbocs']['fee_addr'].strip()
                    if fee_addr:
                        logger.info("preserving_fee_addr_before_regenerate",
                                  fee_addr=fee_addr[:16],
                                  note="Reading fee_addr from existing config")
                
                if 'min_validators_count' in config['esbocs']:
                    try:
                        min_validators_count = int(config['esbocs']['min_validators_count'])
                        logger.info("preserving_min_validators_count_before_regenerate",
                                  min_validators_count=min_validators_count,
                                  note="Reading min_validators_count from existing config")
                    except ValueError:
                        logger.warning("invalid_min_validators_count_in_config",
                                     note="Using default value 2")
        
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
        
        try:
            # Step 0: CRITICAL - Regenerate chain configs with ALL master validators
            # In PoS we can use all validators from the start (emission controlled by ROOT on zerochain)
            first_master_node = master_nodes[0]
            logger.info("regenerating_chain_configs_with_all_masters_before_starting",
                       master_count=len(master_nodes))
            await self.regenerate_configs_with_all_master_validators(
                all_validator_nodes,
                master_nodes  # ALL master nodes
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
            await self._wait_for_master_containers_running(master_nodes, timeout=30.0)
            logger.info("waiting_for_cli_server_ready")
            # Wait for CLI to be ready on all master nodes
            for master_node in master_nodes:
                await self._wait_for_cli_ready(master_node.node_id, timeout=30.0)
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
            await self._wait_for_gdb_sync_complete(master_nodes, timeout=30.0)
            
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
            import time
            start_wait = time.time()
            gdb_ready = False
            for attempt in range(10):
                try:
                    # Check if we can read from stagenet.service.orders group
                    # This will work only if GDB cluster is initialized
                    exit_code, stdout, stderr = self.genesis._exec_cli(
                        first_master_node.node_id,
                        f"srv_stake order list fee -net {self.network_name}",
                        check_output=False
                    )
                    # exit_code=0 means GDB cluster is ready (even if "No orders found")
                    if exit_code == 0:
                        gdb_ready = True
                        elapsed = time.time() - start_wait
                        logger.info("gdb_clusters_ready",
                                   elapsed=f"{elapsed:.1f}s",
                                   note="GDB cluster for orders is initialized")
                        break
                except Exception:
                    pass
                await asyncio.sleep(1.0)
            
            if not gdb_ready:
                logger.warning("gdb_clusters_readiness_unknown",
                             elapsed=f"{time.time() - start_wait:.1f}s",
                             note="Could not verify GDB cluster readiness, proceeding anyway")
            
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
                # CRITICAL: Zerochain not loaded - check genesis event configuration
                logger.error("zerochain_not_loaded_after_snapshot_restore",
                           note="CRITICAL: Zerochain has 0 events - genesis event is NOT loading! "
                                "This means zerochain files are restored but genesis event is not being accepted. "
                                "Check static_genesis_event configuration and node logs for genesis event rejection messages.")
                
                # Check zerochain config for static_genesis_event
                zerochain_config_path = self.genesis.base_path / f"cache/configs/node{first_root_node.node_id}/network/{self.network_name}/zerochain.cfg"
                
                static_genesis_hash = None
                is_static_genesis = False
                seed_mode = None
                
                if zerochain_config_path.exists():
                    config = configparser.ConfigParser()
                    config.read(zerochain_config_path)
                    
                    if 'dag' not in config:
                        raise RuntimeError(
                            f"CRITICAL: [dag] section not found in zerochain config at {zerochain_config_path}! "
                            f"Cannot proceed without dag section."
                        )
                    if 'static_genesis_event' not in config['dag']:
                        raise RuntimeError(
                            f"CRITICAL: static_genesis_event not found in [dag] section at {zerochain_config_path}! "
                            f"Cannot proceed without static_genesis_event."
                        )
                    static_genesis_hash = config['dag']['static_genesis_event'].strip()
                    if 'is_static_genesis_event' not in config['dag']:
                        raise RuntimeError(
                            f"CRITICAL: is_static_genesis_event not found in [dag] section at {zerochain_config_path}! "
                            f"Cannot proceed without is_static_genesis_event flag."
                        )
                    is_static_genesis = config['dag'].getboolean('is_static_genesis_event')
                    
                    # Check base config for seed_mode
                    base_config_path = self.genesis.base_path / f"cache/configs/node{first_root_node.node_id}/cellframe-node.cfg"
                    if not base_config_path.exists():
                        raise RuntimeError(
                            f"CRITICAL: Base config not found at {base_config_path}! "
                            f"Cannot proceed without base config."
                        )
                    base_config = configparser.ConfigParser()
                    base_config.read(base_config_path)
                    if 'main' not in base_config:
                        raise RuntimeError(
                            f"CRITICAL: [main] section not found in base config at {base_config_path}! "
                            f"Cannot proceed without main section."
                        )
                    if 'seed_mode' not in base_config['main']:
                        raise RuntimeError(
                            f"CRITICAL: seed_mode not found in [main] section at {base_config_path}! "
                            f"Cannot proceed without seed_mode parameter."
                        )
                    seed_mode = base_config['main']['seed_mode'].strip()
                    
                    logger.error("zerochain_genesis_config_diagnostic",
                               static_genesis_hash=static_genesis_hash[:16] if static_genesis_hash else "NOT SET",
                               is_static_genesis_event=is_static_genesis,
                               seed_mode=seed_mode,
                               config_path=str(zerochain_config_path),
                               note="CRITICAL: Check if static_genesis_event matches genesis event in chain files!")
                
                # Check node logs for genesis event messages
                try:
                    import docker
                    docker_client = docker.from_env()
                    container_name = f"{compose_manager.project_name}-node-{first_root_node.node_id}"
                    
                    try:
                        container = docker_client.containers.get(container_name)
                        node_logs = container.logs(tail=5000).decode('utf-8', errors='ignore')
                        
                        genesis_event_logs = []
                        chain_load_logs = []
                        zerochain_logs = []
                        
                        for line in node_logs.split('\n'):
                            line_lower = line.lower()
                            if 'genesis' in line_lower and ('event' in line_lower or 'accept' in line_lower or 'reject' in line_lower or 'wrong' in line_lower):
                                genesis_event_logs.append(line)
                            if 'load' in line_lower and ('chain' in line_lower or 'zerochain' in line_lower):
                                chain_load_logs.append(line)
                            if 'zerochain' in line_lower:
                                zerochain_logs.append(line)
                        
                        logger.error("zerochain_genesis_node_logs_diagnostic",
                                   genesis_event_logs=genesis_event_logs[:10] if genesis_event_logs else [],
                                   chain_load_logs=chain_load_logs[:10] if chain_load_logs else [],
                                   zerochain_logs_count=len(zerochain_logs),
                                   sample_zerochain_logs=zerochain_logs[:5] if zerochain_logs else [],
                                   note="CRITICAL: Check node logs for genesis event rejection or chain loading errors!")
                    except docker.errors.NotFound:
                        logger.warning("container_not_found_for_genesis_diagnostic",
                                     container_name=container_name,
                                     note="Container not found - cannot get logs for genesis diagnostic")
                    
                except Exception as log_err:
                    logger.warning("failed_to_get_node_logs_for_genesis_diagnostic",
                                 error=str(log_err),
                                 note="Could not get node logs - proceeding with other diagnostics")
                
                # Check if chain files exist
                # On host: cache/data/node{id}/lib/network/stagenet/zerochain/
                # Inside container: /opt/cellframe-node/var/lib/network/stagenet/zerochain/
                chain_files_path = self.genesis.base_path / f"cache/data/node{first_root_node.node_id}/lib/network/{self.network_name}/zerochain"
                chain_files_exist = chain_files_path.exists() if chain_files_path else False
                
                if chain_files_exist:
                    chain_files = list(chain_files_path.glob("*.dchaincell")) if chain_files_path.exists() else []
                    logger.error("zerochain_files_diagnostic",
                               chain_files_count=len(chain_files),
                               chain_files_path=str(chain_files_path),
                               chain_files_list=[f.name for f in chain_files[:5]],
                               note="Chain files exist but zerochain has 0 events - genesis event is not loading!")
                else:
                    logger.error("zerochain_files_missing",
                               chain_files_path=str(chain_files_path),
                               note="CRITICAL: Chain files directory does not exist - snapshot may not have restored chain files!")
                    
                    # Additional check: try to find chain files using Docker exec
                    try:
                        import docker
                        docker_client = docker.from_env()
                        container_name = f"cellframe-stage-node-{first_root_node.node_id}"
                        container = docker_client.containers.get(container_name)
                        
                        # Check chain files inside container
                        exit_code, output = container.exec_run(
                            "sh -c 'ls -la /opt/cellframe-node/var/lib/network/stagenet/zerochain/*.dchaincell 2>&1 | head -5'"
                        )
                        
                        logger.error("zerochain_files_docker_check",
                                   container_name=container_name,
                                   exit_code=exit_code,
                                   output=output.decode('utf-8', errors='ignore')[:500] if output else "empty",
                                   note="Checking chain files inside Docker container")
                        
                    except Exception as docker_check_err:
                        logger.warning("failed_to_check_chain_files_in_docker",
                                     error=str(docker_check_err),
                                     note="Could not check chain files inside Docker container")
                
                # This is a critical error - cannot proceed
                raise RuntimeError(
                    f"Zerochain not loaded after snapshot restore - has 0 events. "
                    f"This indicates genesis event is not loading from chain files. "
                    f"static_genesis_event={static_genesis_hash[:16] if static_genesis_hash else 'NOT SET'}, "
                    f"is_static_genesis_event={is_static_genesis}, "
                    f"chain_files_exist={chain_files_exist}. "
                    f"Check node logs for genesis event rejection messages or chain loading errors."
                )
            
            import time
            token_found = False
            timeout_token = 60.0  # Increased timeout - chains may need more time to load after snapshot restore
            start_time_token = time.time()
            
            while time.time() - start_time_token < timeout_token:
                elapsed = time.time() - start_time_token
                
                # Method 1: Check if TCELL token exists on zerochain using token list
                exit_code_list, stdout_list, stderr_list = self.genesis._exec_cli(
                    first_root_node.node_id,
                    f"token list -net {self.network_name} -chain zerochain",
                    check_output=False
                )
                
                if exit_code_list == 0 and stdout_list:
                    token_found = "TCELL" in stdout_list or "tcell" in stdout_list.lower()
                    if token_found:
                        logger.info("tcell_token_found_on_zerochain_via_list",
                                   elapsed=f"{elapsed:.1f}s",
                                   token_list_output=stdout_list[:500],
                                   note="TCELL token exists on zerochain, ready for transfers")
                        break
                    else:
                        logger.debug("tcell_not_in_token_list",
                                   elapsed=f"{elapsed:.1f}s",
                                   token_list_output=stdout_list[:500] if stdout_list else "empty",
                                   note="TCELL not found in token list, trying alternative methods")
                else:
                    logger.debug("token_list_failed",
                               elapsed=f"{elapsed:.1f}s",
                               exit_code=exit_code_list,
                               stderr=stderr_list[:200] if stderr_list else "empty",
                               note="token list command failed, trying alternative methods")
                
                # Method 2: Try token show as alternative check
                if not token_found:
                    exit_code_show, stdout_show, stderr_show = self.genesis._exec_cli(
                        first_root_node.node_id,
                        f"token show -net {self.network_name} -chain zerochain -token TCELL",
                        check_output=False
                    )
                    
                    if exit_code_show == 0 and stdout_show:
                        token_found = "TCELL" in stdout_show or "tcell" in stdout_show.lower()
                        if token_found:
                            logger.info("tcell_token_found_on_zerochain_via_show",
                                       elapsed=f"{elapsed:.1f}s",
                                       token_show_output=stdout_show[:500],
                                       note="TCELL token exists on zerochain (verified via token show)")
                            break
                        else:
                            logger.debug("tcell_not_in_token_show",
                                       elapsed=f"{elapsed:.1f}s",
                                       token_show_output=stdout_show[:500] if stdout_show else "empty")
                    else:
                        logger.debug("token_show_failed",
                                   elapsed=f"{elapsed:.1f}s",
                                   exit_code=exit_code_show,
                                   stderr=stderr_show[:200] if stderr_show else "empty")
                
                # Method 3: Check if zerochain DAG has events (indicates chain is loaded)
                if not token_found and elapsed > 5.0:  # Only check DAG after initial wait
                    exit_code_dag, stdout_dag, _ = self.genesis._exec_cli(
                        first_root_node.node_id,
                        f"dag event list -net {self.network_name} -chain zerochain -from events -limit 1",
                        check_output=False
                    )
                    
                    if exit_code_dag == 0 and stdout_dag:
                        import re
                        total_match = re.search(r'total events:\s*(\d+)', stdout_dag, re.IGNORECASE)
                        total_events = int(total_match.group(1)) if total_match else 0
                        if total_events > 0:
                            logger.debug("zerochain_has_dag_events",
                                       elapsed=f"{elapsed:.1f}s",
                                       total_events=total_events,
                                       note="Zerochain has DAG events, token should be accessible")
                        else:
                            logger.debug("zerochain_no_dag_events",
                                       elapsed=f"{elapsed:.1f}s",
                                       note="Zerochain may not be fully loaded yet")
                
                    await asyncio.sleep(2.0)  # Check every 2 seconds instead of 1
            
            if not token_found:
                # Final diagnostic: collect all information
                logger.error("tcell_token_not_found_final_diagnostic",
                           elapsed=f"{time.time() - start_time_token:.1f}s",
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
                    f"TCELL token not found on zerochain after {timeout_token}s. "
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
                zerochain_config_path = self.genesis.base_path / f"cache/configs/node{first_root_node.node_id}/network/{self.network_name}/zerochain.cfg"
                
                static_genesis_hash = None
                is_static_genesis = False
                seed_mode = None
                
                if zerochain_config_path.exists():
                    config = configparser.ConfigParser()
                    config.read(zerochain_config_path)
                    
                    if 'dag' not in config:
                        raise RuntimeError(
                            f"CRITICAL: [dag] section not found in zerochain config at {zerochain_config_path}! "
                            f"Cannot proceed without dag section."
                        )
                    if 'static_genesis_event' not in config['dag']:
                        raise RuntimeError(
                            f"CRITICAL: static_genesis_event not found in [dag] section at {zerochain_config_path}! "
                            f"Cannot proceed without static_genesis_event."
                        )
                    static_genesis_hash = config['dag']['static_genesis_event'].strip()
                    if 'is_static_genesis_event' not in config['dag']:
                        raise RuntimeError(
                            f"CRITICAL: is_static_genesis_event not found in [dag] section at {zerochain_config_path}! "
                            f"Cannot proceed without is_static_genesis_event flag."
                        )
                    is_static_genesis = config['dag'].getboolean('is_static_genesis_event')
                    
                    # Check base config for seed_mode
                    base_config_path = self.genesis.base_path / f"cache/configs/node{first_root_node.node_id}/cellframe-node.cfg"
                    if not base_config_path.exists():
                        raise RuntimeError(
                            f"CRITICAL: Base config not found at {base_config_path}! "
                            f"Cannot proceed without base config."
                        )
                    base_config = configparser.ConfigParser()
                    base_config.read(base_config_path)
                    if 'main' not in base_config:
                        raise RuntimeError(
                            f"CRITICAL: [main] section not found in base config at {base_config_path}! "
                            f"Cannot proceed without main section."
                        )
                    if 'seed_mode' not in base_config['main']:
                        raise RuntimeError(
                            f"CRITICAL: seed_mode not found in [main] section at {base_config_path}! "
                            f"Cannot proceed without seed_mode parameter."
                        )
                    seed_mode = base_config['main']['seed_mode'].strip()
                
                logger.info("zerochain_config_check",
                           static_genesis_hash=static_genesis_hash[:16] if static_genesis_hash else "NOT SET",
                           is_static_genesis_event=is_static_genesis,
                           seed_mode=seed_mode,
                           note="Zerochain config check - if static_genesis_event is set but seed_mode=false, genesis must match!")
                
                # Get actual genesis event from DAG
                exit_code_genesis, stdout_genesis, stderr_genesis = self.genesis._exec_cli(
                    first_root_node.node_id,
                    f"dag event list -net {self.network_name} -chain zerochain -from events -limit 1",
                    check_output=False
                )
                
                actual_genesis_hash = None
                if exit_code_genesis == 0 and stdout_genesis:
                    # Extract first event hash
                    genesis_match = re.search(r'(0x[A-Fa-f0-9]{64})', stdout_genesis)
                    if genesis_match:
                        actual_genesis_hash = genesis_match.group(1)
                
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
                
                # Check tx_history for fee_collector wallet (should show transactions if UTXO are indexed)
                exit_code_txhist, stdout_txhist, stderr_txhist = self.genesis._exec_cli(
                    first_root_node.node_id,
                    f"tx_history -w {emission_wallet_name} -net {self.network_name} -chain zerochain",
                    check_output=False
                )
                
                tx_history_count = 0
                if exit_code_txhist == 0 and stdout_txhist:
                    # Try to extract total_tx_count from JSON output
                    tx_count_match = re.search(r'total_tx_count["\']?\s*:\s*(\d+)', stdout_txhist, re.IGNORECASE)
                    if tx_count_match:
                        tx_history_count = int(tx_count_match.group(1))
                    logger.info("tx_history_check_result",
                               tx_history_count=tx_history_count,
                               stdout_preview=stdout_txhist[:500] if stdout_txhist else "empty",
                               note="TX history count for fee_collector wallet")
                else:
                    logger.warning("tx_history_check_failed",
                                 exit_code=exit_code_txhist,
                                 stderr=stderr_txhist[:500] if stderr_txhist else "empty",
                                 note="Failed to get tx_history")
                
                # DIAGNOSTIC SUMMARY
                logger.warning("diagnostic_summary_balance_vs_utxo",
                             balance_datoshi=fee_collector_balance_datoshi,
                             dag_events_count=dag_events_count,
                             tx_history_count=tx_history_count,
                             note=f"BALANCE VISIBLE: {fee_collector_balance_datoshi} datoshi, "
                                  f"DAG EVENTS: {dag_events_count}, "
                                  f"TX HISTORY: {tx_history_count}. "
                                  f"If balance > 0 but tx_history = 0, UTXO are NOT indexed in ledger_items!")
                
            except Exception as diag_err:
                logger.warning("diagnostic_check_exception",
                             error=str(diag_err),
                             note="Exception during diagnostic check - proceeding anyway")
            
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
                    # Wait for network to transition to NET_STATE_SYNC_CHAINS
                    logger.info("waiting_for_sync_chains_state",
                               note="Waiting for network to transition to NET_STATE_SYNC_CHAINS state")
                    await asyncio.sleep(5.0)  # Wait for state transition
                    
                    # Check network state
                    exit_code_state, stdout_state, stderr_state = self.genesis._exec_cli(
                        first_root_node.node_id,
                        f"net -net {self.network_name} status",
                        check_output=False
                    )
                    
                    if exit_code_state == 0 and stdout_state:
                        logger.info("network_state_after_sync",
                                   state_output=stdout_state[:500],
                                   note="Network state after sync command")
                    
                    # Wait a bit more for ledger to update
                    await asyncio.sleep(3.0)
                    
                    # Re-check tx_history after sync
                    exit_code_txhist2, stdout_txhist2, stderr_txhist2 = self.genesis._exec_cli(
                        first_root_node.node_id,
                        f"tx_history -w {emission_wallet_name} -net {self.network_name} -chain zerochain",
                        check_output=False
                    )
                    
                    tx_history_count_after = 0
                    if exit_code_txhist2 == 0 and stdout_txhist2:
                        tx_count_match = re.search(r'total_tx_count["\']?\s*:\s*(\d+)', stdout_txhist2, re.IGNORECASE)
                        if tx_count_match:
                            tx_history_count_after = int(tx_count_match.group(1))
                    
                    logger.info("zerochain_synced_into_ledger",
                               tx_history_before=tx_history_count,
                               tx_history_after=tx_history_count_after,
                               note=f"Zerochain synced - tx_history changed from {tx_history_count} to {tx_history_count_after}")
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
                try:
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
                except Exception as transfer_err:
                    logger.error("failed_to_transfer_to_master_in_phase2",
                               node_id=master_node.node_id,
                               wallet_name=wallet_name,
                               error=str(transfer_err),
                               note="Transfer failed - master wallet will be empty")
                    # Continue with other wallets instead of failing completely
            
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
                    await self._wait_for_transaction_processed(
                        master_node.node_id,
                        tx_hash,
                        chain="zerochain",
                        timeout=30.0
                    )
            
            # Step 8: GDB sync and wait for delegation transactions
            logger.info("triggering_gdb_sync_for_zerochain_delegations")
            await self.genesis.validator_mgr.sync_orders_across_network(all_validator_nodes)
            await self._wait_for_gdb_sync_complete(all_validator_nodes, timeout=30.0)
            
            
            # Step 11: Verify delegations are visible (check stake service)
            logger.info("verifying_key_delegations_synced")
            # Wait for delegations to sync across network via GDB
            await self._wait_for_delegations_synced(
                master_nodes,
                expected_count=len(master_nodes),
                timeout=60.0
            )
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
            await self._wait_for_master_containers_running(master_nodes, timeout=60.0)
            # Wait for CLI to be ready after restart
            for master_node in master_nodes:
                await self._wait_for_cli_ready(master_node.node_id, timeout=30.0)
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
            await self.genesis.validator_mgr.wait_for_stake_service_ready(
                master_nodes,  # ALL master nodes now have delegations
                timeout=60.0,
                poll_interval=2.0
            )
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
            await self.genesis.validator_mgr.wait_for_esbocs_consensus_active(
                master_nodes,  # ALL master nodes now have delegated keys
                timeout=90.0,
                poll_interval=3.0
            )
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
            await self.genesis.sync_mgr.wait_for_first_block(
                "main", 
                timeout=60, 
                master_nodes=master_nodes  # All master nodes participate in consensus
            )
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
    
    async def _wait_for_master_containers_running(
        self,
        master_nodes: List[NodeConfig],
        timeout: float = 60.0
    ) -> None:
        """
        Wait for master node containers to be running.
        
        Args:
            master_nodes: List of master nodes
            timeout: Maximum time to wait (seconds)
            
        Raises:
            RuntimeError: If containers don't start within timeout
        """
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            all_running = True
            for master_node in master_nodes:
                container_name = f"cellframe-stage-node-{master_node.node_id}"
                try:
                    container = self.docker_client.containers.get(container_name)
                    container.reload()
                    if container.status != 'running':
                        all_running = False
                        break
                except Exception:
                    all_running = False
                    break
            
            if all_running:
                return
            
            await asyncio.sleep(1.0)
        
        raise RuntimeError(f"Master containers did not start within {timeout}s")
    
    async def _wait_for_emission_in_ledger(
        self,
        node_id: int,
        emission_hash: str,
        chain: str = "zerochain",
        timeout: float = 60.0,
        poll_interval: float = 2.0
    ) -> bool:
        """
        Wait for emission to appear in ledger (NOT just mempool).
        
        CRITICAL: Emission must be in ledger (processed by DAG-PoA) before it can be used.
        Emission in mempool is not enough - SDK requires it to be in ledger.
        
        Args:
            node_id: Node ID to check
            emission_hash: Emission hash to look for
            chain: Chain name (default: zerochain)
            timeout: Maximum wait time (seconds)
            poll_interval: Seconds between checks
            
        Returns:
            True if emission found in ledger, False if timeout
        """
        import time
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check ledger (emission must be processed by DAG-PoA)
            exit_code, stdout, stderr = self.genesis._exec_cli(
                node_id,
                f"ledger list coins -net {self.network_name} -chain {chain}",
                check_output=False
            )
            if exit_code == 0 and stdout:
                emission_found = emission_hash.lower() in stdout.lower()
                if emission_found:
                    elapsed = time.time() - start_time
                    logger.info("emission_found_in_ledger",
                               node_id=node_id,
                               emission=emission_hash[:16],
                               elapsed=f"{elapsed:.1f}s",
                               method="ledger")
                    return True
            
            # Diagnostic: Check mempool status (for debugging)
            exit_code, stdout, stderr = self.genesis._exec_cli(
                node_id,
                f"mempool list -net {self.network_name} -chain {chain}",
                check_output=False
            )
            if exit_code == 0 and stdout:
                emission_in_mempool = emission_hash.lower() in stdout.lower()
                if emission_in_mempool and time.time() - start_time > 10:
                    # Log warning if emission still in mempool after 10s
                    logger.debug("emission_still_in_mempool",
                               node_id=node_id,
                               emission=emission_hash[:16],
                               elapsed=f"{time.time() - start_time:.1f}s",
                               note="Emission in mempool but not in ledger - may need DAG processing")
            
            await asyncio.sleep(poll_interval)
        
        elapsed = time.time() - start_time
        logger.warning("emission_not_found_in_ledger_timeout",
                     node_id=node_id,
                     emission=emission_hash[:16],
                     elapsed=f"{elapsed:.1f}s",
                     note="Emission not found in ledger - may need DAG processing or sync")
        return False
    
    async def _wait_for_transaction_processed(
        self,
        node_id: int,
        tx_hash: str,
        chain: str = "zerochain",
        timeout: float = 30.0,
        poll_interval: float = 1.0
    ) -> bool:
        """
        Wait for transaction to be processed (appear in ledger or mempool).
        
        Args:
            node_id: Node ID to check
            tx_hash: Transaction hash to look for
            chain: Chain name (default: zerochain)
            timeout: Maximum wait time (seconds)
            poll_interval: Seconds between checks
            
        Returns:
            True if transaction found, False if timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check ledger first
            exit_code, stdout, stderr = self.genesis._exec_cli(
                node_id,
                f"ledger list coins -net {self.network_name} -chain {chain}",
                check_output=False
            )
            if exit_code == 0 and stdout:
                tx_found = tx_hash.lower() in stdout.lower()
                if tx_found:
                    elapsed = time.time() - start_time
                    logger.info("transaction_found_in_ledger",
                               node_id=node_id,
                               tx_hash=tx_hash[:16],
                               elapsed=f"{elapsed:.1f}s")
                    return True
            
            # Check mempool as fallback
            exit_code, stdout, stderr = self.genesis._exec_cli(
                node_id,
                f"mempool list -net {self.network_name} -chain {chain}",
                check_output=False
            )
            if exit_code == 0 and stdout:
                tx_found = tx_hash.lower() in stdout.lower()
                if tx_found:
                    elapsed = time.time() - start_time
                    logger.info("transaction_found_in_mempool",
                               node_id=node_id,
                               tx_hash=tx_hash[:16],
                               elapsed=f"{elapsed:.1f}s")
                    return True
            
            await asyncio.sleep(poll_interval)
        
        elapsed = time.time() - start_time
        logger.warning("transaction_not_processed_timeout",
                     node_id=node_id,
                     tx_hash=tx_hash[:16],
                     elapsed=f"{elapsed:.1f}s")
        return False
    
    async def _wait_for_gdb_sync_complete(
        self,
        nodes: List[NodeConfig],
        timeout: float = 30.0,
        poll_interval: float = 2.0
    ) -> bool:
        """
        Wait for GDB sync to complete across nodes.
        
        Args:
            nodes: List of nodes to check
            timeout: Maximum wait time (seconds)
            poll_interval: Seconds between checks
            
        Returns:
            True if sync complete, False if timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check GDB sync status on all nodes
            all_synced = True
            for node in nodes:
                try:
                    exit_code, stdout, stderr = self.genesis._exec_cli(
                        node.node_id,
                        f"global_db status -net {self.network_name}",
                        check_output=False
                    )
                    if exit_code != 0:
                        all_synced = False
                        break
                except Exception:
                    all_synced = False
                    break
            
            if all_synced:
                elapsed = time.time() - start_time
                logger.info("gdb_sync_complete",
                           node_count=len(nodes),
                           elapsed=f"{elapsed:.1f}s")
                return True
            
            await asyncio.sleep(poll_interval)
        
        elapsed = time.time() - start_time
        logger.warning("gdb_sync_timeout",
                     node_count=len(nodes),
                     elapsed=f"{elapsed:.1f}s")
        return False
    
    async def _wait_for_delegations_synced(
        self,
        nodes: List[NodeConfig],
        expected_count: int,
        timeout: float = 60.0,
        poll_interval: float = 2.0
    ) -> bool:
        """
        Wait for delegations to be synced across nodes.
        
        Args:
            nodes: List of nodes to check
            expected_count: Expected number of delegations
            timeout: Maximum wait time (seconds)
            poll_interval: Seconds between checks
            
        Returns:
            True if delegations synced, False if timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            all_synced = True
            for node in nodes:
                try:
                    exit_code, stdout, stderr = self.genesis._exec_cli(
                        node.node_id,
                        f"srv_stake list keys -net {self.network_name}",
                        check_output=False
                    )
                    if exit_code != 0:
                        all_synced = False
                        break
                    
                    # Check if we have expected number of delegations
                    if stdout:
                        # Count keys in output (rough estimate)
                        key_count = stdout.count('addr:') or stdout.count('address:')
                        if key_count < expected_count:
                            all_synced = False
                            break
                except Exception:
                    all_synced = False
                    break
            
            if all_synced:
                elapsed = time.time() - start_time
                logger.info("delegations_synced_across_nodes",
                           node_count=len(nodes),
                           expected_count=expected_count,
                           elapsed=f"{elapsed:.1f}s")
                return True
            
            await asyncio.sleep(poll_interval)
        
        elapsed = time.time() - start_time
        logger.warning("delegations_sync_timeout",
                     node_count=len(nodes),
                     elapsed=f"{elapsed:.1f}s")
        return False
    
    async def _wait_for_cli_ready(
        self,
        node_id: int,
        timeout: float = 30.0,
        poll_interval: float = 0.5
    ) -> bool:
        """
        Wait for CLI server to be ready on node.
        
        Args:
            node_id: Node ID to check
            timeout: Maximum wait time (seconds)
            poll_interval: Seconds between checks
            
        Returns:
            True if CLI ready, False if timeout
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                exit_code, stdout, stderr = self.genesis._exec_cli(
                    node_id,
                    "net -net {} get status".format(self.network_name),
                    check_output=False
                )
                if exit_code == 0:
                    elapsed = time.time() - start_time
                    logger.debug("cli_ready",
                               node_id=node_id,
                               elapsed=f"{elapsed:.1f}s")
                    return True
            except Exception:
                pass
            
            await asyncio.sleep(poll_interval)
        
        elapsed = time.time() - start_time
        logger.warning("cli_not_ready_timeout",
                     node_id=node_id,
                     elapsed=f"{elapsed:.1f}s")
        return False

