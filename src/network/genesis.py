"""
Genesis initialization for stagenet.

Handles initial setup tasks after network start:
- Creating validator stake orders
- Registering node aliases in GDB
- Setting up initial state
"""

import asyncio
from pathlib import Path
from typing import List, Dict, Optional
import docker
import time

from ..utils.logger import get_logger
from .models import NodeConfig

logger = get_logger(__name__)


class GenesisInitializer:
    """Initialize genesis state for stagenet."""
    
    def __init__(self, base_path: Path, network_name: str = "stagenet", config_path: Path = None):
        """
        Initialize genesis initializer.
        
        Args:
            base_path: Base path to stage-env directory
            network_name: Network name (default: stagenet)
            config_path: Optional path to config file
        """
        self.base_path = base_path
        self.network_name = network_name
        self.docker_client = docker.from_env()
        # Load cache dir from config
        from ..config.loader import ConfigLoader
        config_loader = ConfigLoader(base_path, config_path)
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', 'cache')
        # Resolve cache dir relative to BASE_PATH (always)
        self.certs_cache = (base_path / cache_dir_relative / "certs").resolve()
        
        self.cli_config_path = "/opt/cellframe-node/etc/cellframe-node.cfg"
        
        # Initialize specialized managers for modular architecture
        from .genesis_config import GenesisConfigManager
        from .genesis_token import TokenGenesisManager
        from .genesis_sync import ChainSyncManager
        
        self.config_mgr = GenesisConfigManager(base_path, network_name)
        self.token_mgr = TokenGenesisManager(base_path, network_name)
        self.sync_mgr = ChainSyncManager(base_path, network_name)
        
        logger.info("genesis_initializer_created", network=network_name)
    
    def _exec_cli(self, node_id: int, command: str, check_output: bool = True) -> tuple:
        """
        Execute CLI command in specified node container.
        
        Универсальный метод для вызова cellframe-node-cli в Docker контейнере.
        Автоматически добавляет путь к конфигу для использования Unix socket.
        
        Args:
            node_id: ID ноды (1, 2, 3, etc.)
            command: CLI команда БЕЗ префикса 'cellframe-node-cli' 
                    Например: "node list -net stagenet"
            check_output: Выбрасывать исключение при ненулевом exit code
            
        Returns:
            Tuple[int, str, str]: (exit_code, stdout, stderr)
            
        Raises:
            RuntimeError: Если контейнер не найден или команда упала (при check_output=True)
            
        Example:
            exit_code, stdout, stderr = self._exec_cli(1, "node list -net stagenet")
        """
        container_name = f"cellframe-stage-node-{node_id}"
        
        try:
            container = self.docker_client.containers.get(container_name)
        except Exception as e:
            raise RuntimeError(f"Container {container_name} not found: {e}")
        
        # Собираем полную команду как ОДНУ строку и выполняем через sh -c
        # Это предотвращает JSON-RPC fallback и неправильное разделение аргументов
        # NOTE: cellframe-node-cli НЕ поддерживает -c, он ищет конфиг в g_sys_dir_path/etc
        full_cmd = f"cellframe-node-cli {command}"
        cmd = ["sh", "-c", full_cmd]
        
        # Выполняем команду
        result = container.exec_run(cmd, demux=True)
        exit_code = result.exit_code
        stdout, stderr = result.output
        
        stdout_str = stdout.decode('utf-8').strip() if stdout else ""
        stderr_str = stderr.decode('utf-8').strip() if stderr else ""
        
        if check_output and exit_code != 0:
            raise RuntimeError(
                f"CLI command failed in node-{node_id}: {command}\n"
                f"Exit code: {exit_code}\n"
                f"Stderr: {stderr_str}\n"
                f"Stdout: {stdout_str}"
            )
        
        return exit_code, stdout_str, stderr_str
    
    def _read_node_addr_with_retry(
        self, 
        node_id: int, 
        max_retries: int = 10, 
        retry_delay: float = 1.0
    ) -> Optional[str]:
        """
        Read node_addr.txt from HOST filesystem (not container).
        
        The file is created by cert-generator on the host in certs_cache/nodeN/node_addr.txt
        and is NOT copied into the container.
        
        Args:
            node_id: Node ID
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
            
        Returns:
            Node address string or None if failed
        """
        addr_file = self.certs_cache / f"node{node_id}" / "node_addr.txt"
        
        for attempt in range(1, max_retries + 1):
            try:
                if addr_file.exists():
                    node_addr = addr_file.read_text().strip()
                    if node_addr:  # Ensure non-empty
                        logger.debug("read_node_address",
                                    node_id=node_id,
                                    node_addr=node_addr,
                                    attempt=attempt,
                                    source="host_filesystem")
                        return node_addr
                
                # File not ready yet
                if attempt < max_retries:
                    logger.debug("node_addr_not_ready_retrying",
                                node_id=node_id,
                                attempt=attempt,
                                max_retries=max_retries,
                                path=str(addr_file))
                    time.sleep(retry_delay)
                    
            except Exception as e:
                if attempt < max_retries:
                    logger.debug("node_addr_read_error_retrying",
                                node_id=node_id,
                                attempt=attempt,
                                error=str(e))
                    time.sleep(retry_delay)
                else:
                    logger.error("failed_to_get_node_address",
                                node_id=node_id,
                                error=str(e),
                                attempts=attempt)
        
        logger.error("failed_to_read_node_addr_after_retries",
                    node_id=node_id,
                    max_retries=max_retries,
                    path=str(addr_file),
                    exists=addr_file.exists())
        return None
    
    async def initialize(self, nodes: List[NodeConfig]) -> None:
        """
        Initialize genesis state.
        
        For TCELL genesis, we only need certificates to be in place.
        Validator orders are NOT needed - certificates are configured in chain configs.
        
        Args:
            nodes: List of node configurations
        """
        logger.info("starting_genesis_initialization", nodes=len(nodes))
        
        # Find root nodes (for DAG-PoA on zerochain)
        root_nodes = [n for n in nodes if n.is_seed_node]
        
        if not root_nodes:
            logger.warning("no_root_nodes_found")
            return
        
        logger.info("found_root_nodes_for_dag_poa", count=len(root_nodes))
        
        # Wait a bit for nodes to initialize
        logger.info("waiting_for_node_initialization")
        await asyncio.sleep(5)
        
        # Root nodes will connect to each other via seed_nodes_hosts configuration
        # DAG-PoA consensus is configured via auth_certs_prefix in zerochain.cfg
        # Certificates (stagenet.master.N.dcert) are already in place from CertGenerator
        logger.info("root_nodes_will_connect_via_seed_nodes_hosts",
                   seed_nodes=len(root_nodes))
        
        logger.info("genesis_initialization_complete", 
                   note="DAG-PoA certificates configured via chain config")
    
    async def _setup_root_nodelists(self, root_nodes: List[NodeConfig]) -> None:
        """
        Setup nodelists for root nodes - each root node adds all other root nodes.
        
        Root nodes are the bootstrap/seed nodes that manage the network topology.
        They need to know about each other immediately.
        
        Args:
            root_nodes: List of root node configurations
        """
        logger.info("setting_up_root_nodelists", count=len(root_nodes))
        
        # Read all root node addresses first (from containers, not host)
        root_node_data = []
        for node in root_nodes:
            # Use retry logic to read node_addr.txt
            node_addr = self._read_node_addr_with_retry(node.node_id)
            
            if node_addr:
                root_node_data.append({
                    'node': node,
                    'validator_addr': node_addr,  # Same as node_addr
                    'node_addr': node_addr
                })
            else:
                logger.warning("skipping_node_no_address",
                              node_id=node.node_id)
        
        # For each root node, add all other root nodes to its nodelist
        for current in root_node_data:
            container_name = f"cellframe-stage-node-{current['node'].node_id}"
            
            try:
                container = self.docker_client.containers.get(container_name)
            except docker.errors.NotFound:
                logger.warning("root_node_container_not_found",
                              node_id=current['node'].node_id,
                              container=container_name)
                continue
            
            # Add this node itself first
            await self._add_to_nodelist(
                container,
                current['node'],
                current['node_addr'],
                current['node'].ip_address,
                current['node'].node_port,
                is_self=True
            )
            
            # Then add all other root nodes
            for other in root_node_data:
                if other['node'].node_id == current['node'].node_id:
                    continue  # Skip self (already added)
                
                await self._add_to_nodelist(
                    container,
                    current['node'],
                    other['node_addr'],
                    other['node'].ip_address,
                    other['node'].node_port,
                    is_self=False
                )
        
        logger.info("root_nodelists_setup_complete")
    
    async def _add_to_nodelist(
        self,
        container: docker.models.containers.Container,
        current_node: NodeConfig,
        target_node_addr: str,
        target_ip: str,
        target_port: int,
        is_self: bool = False
    ) -> None:
        """
        Add a node to current node's nodelist.
        
        Args:
            container: Docker container of current node
            current_node: Current node configuration
            target_node_addr: Node address to add (hex format)
            target_ip: IP address of target node
            target_port: Port of target node
            is_self: Whether adding the node itself
        """
        # Use unified CLI method
        logger.info("adding_to_nodelist",
                   current_node_id=current_node.node_id,
                   target_addr=target_node_addr,
                   target_endpoint=f"{target_ip}:{target_port}",
                   is_self=is_self)
        
        try:
            exit_code, stdout_str, stderr_str = self._exec_cli(
                current_node.node_id,
                f"node add -net {self.network_name} -addr {target_node_addr}",
                check_output=False
            )
            
            if exit_code != 0:
                # Some errors are expected (e.g., node already in list)
                if "already" in stderr_str.lower() or "already" in stdout_str.lower():
                    logger.debug("node_already_in_nodelist",
                                current_node_id=current_node.node_id,
                                target_addr=target_node_addr)
                else:
                    logger.warning("nodelist_add_failed",
                                  current_node_id=current_node.node_id,
                                  target_addr=target_node_addr,
                                  exit_code=exit_code,
                                  stderr=stderr_str)
            else:
                logger.info("added_to_nodelist",
                           current_node_id=current_node.node_id,
                           target_addr=target_node_addr,
                           output=stdout_str.strip())
                
        except Exception as e:
            logger.exception("nodelist_add_exception",
                           current_node_id=current_node.node_id,
                           target_addr=target_node_addr,
                           error=str(e))
    
    async def _create_validator_order(
        self,
        container: docker.models.containers.Container,
        node: NodeConfig
    ) -> None:
        """
        Create validator order for a node.
        
        Args:
            container: Docker container to execute commands in
            node: Node configuration
        """
        # Certificate name for this validator
        # NOTE: Must use pvt. prefix for private key! Both validator_create and CLI commands need it.
        validator_idx = node.node_id - 1
        cert_name = f"pvt.{self.network_name}.master.{validator_idx}"
        
        # Read node address with retry logic
        node_addr = self._read_node_addr_with_retry(node.node_id)
        
        if not node_addr:
            logger.error("cannot_create_order_no_node_addr",
                        node_id=node.node_id)
            return
        
        logger.info("read_node_address",
                   node_id=node.node_id,
                   node_addr=node_addr)
        
        # Order parameters
        # value_min and value_max in datoshi (1 token = 10^18 datoshi)
        # For testing, use 100 tokens min, 10000 tokens max
        value_min = "100000000000000000000"  # 100 tokens
        value_max = "10000000000000000000000"  # 10000 tokens
        tax = "10.0"  # 10.0% tax (must be float с точкой)
        
        # Use unified CLI method
        logger.info("creating_validator_order",
                   node_id=node.node_id,
                   cert=cert_name,
                   node_addr=node_addr)
        
        try:
            exit_code, stdout_str, stderr_str = self._exec_cli(
                node.node_id,
                f"srv_stake order create validator -net {self.network_name} -value_min {value_min} -value_max {value_max} -tax {tax} -cert {cert_name} -node_addr {node_addr} -H hex",
                check_output=False
            )
            
            if exit_code != 0:
                logger.error("order_creation_failed",
                           node_id=node.node_id,
                           exit_code=exit_code,
                           stdout=stdout_str,
                           stderr=stderr_str)
                raise RuntimeError(f"Failed to create order for node {node.node_id}: {stderr_str}")
            
            logger.info("validator_order_created",
                       node_id=node.node_id,
                       cert=cert_name,
                       output=stdout_str.strip())
            
        except Exception as e:
            logger.exception("order_creation_exception",
                           node_id=node.node_id,
                           error=str(e))
            raise
    
    async def register_node_aliases(self, nodes: List[NodeConfig]) -> None:
        """
        Register node aliases in GDB for node discovery.
        
        This allows nodes to find each other by validator address.
        
        Args:
            nodes: List of node configurations
        """
        logger.info("registering_node_aliases", count=len(nodes))
        
        # Use first node as admin
        admin_node = nodes[0]
        container_name = f"cellframe-stage-node-{admin_node.node_id}"
        
        try:
            container = self.docker_client.containers.get(container_name)
        except docker.errors.NotFound:
            logger.error("admin_node_container_not_found", container=container_name)
            raise RuntimeError(f"Container {container_name} not found")
        
        # Register each node
        for node in nodes:
            # Read node address with retry logic
            node_addr = self._read_node_addr_with_retry(node.node_id)
            
            if not node_addr:
                logger.warning("skipping_node_alias_no_address",
                              node_id=node.node_id)
                continue
            
            # Use unified CLI method for GDB set
            logger.info("registering_node_alias",
                       node_id=node.node_id,
                       node_addr=node_addr,
                       endpoint=f"{node.ip_address}:{node.node_port}")
            
            try:
                exit_code, stdout_str, stderr_str = self._exec_cli(
                    node.node_id,
                    f"global_db set -net {self.network_name} node_alias.{node_addr} {node.ip_address}:{node.node_port}",
                    check_output=False
                )
                
                if exit_code != 0:
                    logger.warning("node_alias_registration_failed",
                                  node_id=node.node_id,
                                  exit_code=exit_code,
                                  stderr=stderr_str)
                else:
                    logger.info("node_alias_registered",
                              node_id=node.node_id,
                              node_addr=node_addr)
                    
            except Exception as e:
                logger.exception("node_alias_registration_exception",
                               node_id=node.node_id,
                               error=str(e))
        
        logger.info("node_alias_registration_complete")
        
        # Bring all nodes online explicitly (in case auto_online didn't work)
        logger.info("bringing_nodes_online")
        for node in nodes:
            try:
                exit_code, stdout, stderr = self._exec_cli(
                    node.node_id,
                    f"net -net {self.network_name} go online",
                    check_output=False
                )
                
                if exit_code == 0:
                    logger.info("node_brought_online", node_id=node.node_id)
                else:
                    logger.warning("failed_to_bring_node_online",
                                  node_id=node.node_id,
                                  stderr=stderr)
            except Exception as e:
                logger.warning("exception_bringing_node_online",
                              node_id=node.node_id,
                              error=str(e))
    
    async def register_all_nodes_via_cli(self, nodes: List[NodeConfig]) -> None:
        """
        Register ALL nodes via CLI 'node add' command from node1 (ROOT node with admin rights).
        
        CRITICAL: Only ROOT nodes have rights to modify node list!
        Node list then propagates via GDB sync over established links.
        
        Args:
            nodes: List of all node configurations
        """
        logger.info("registering_nodes_via_cli_from_node1", total_nodes=len(nodes))
        
        # Prepare registration tasks: node1 registers ALL nodes (including itself)
        async def register_single_node(target_node: NodeConfig) -> bool:
            """
            Register target_node from node1 (admin node).
            Returns True on success.
            """
            
            # Get target node address from its running container
            try:
                exit_code, stdout_str, stderr = self._exec_cli(
                    target_node.node_id,
                    f"node dump -net {self.network_name}",
                    check_output=False
                )
                
                if exit_code != 0:
                    logger.warning("skipping_registration_dump_failed",
                                  target=target_node.node_id,
                                  stderr=stderr)
                    return False
                
                # Parse target node address
                import re
                addr_match = re.search(r'Node addr:\s+([0-9A-Fa-f:]+)', stdout_str)
                if not addr_match:
                    logger.warning("skipping_registration_no_address",
                                  target=target_node.node_id,
                                  dump_output=stdout_str[:200])
                    return False
                
                target_addr = addr_match.group(1)
                
            except Exception as e:
                logger.warning("failed_to_fetch_address",
                              target=target_node.node_id,
                              error=str(e))
                return False
            
            # Register target_node on node1's node list (will propagate via GDB)
            logger.debug("registering_node_from_node1",
                       target=target_node.node_id,
                       target_addr=target_addr[:20] + "...")
            
            try:
                exit_code, stdout_str, stderr_str = self._exec_cli(
                    1,  # Always register FROM node1 (ROOT with admin rights)
                    f"node add -net {self.network_name} -addr {target_addr} -host {target_node.ip_address} -port {target_node.node_port}",
                    check_output=False
                )
                
                if exit_code == 0:
                    # Check for success/warning messages
                    if "You have no access rights" in stdout_str:
                        logger.warning("node_add_no_rights",
                                      target=target_node.node_id)
                        return False
                    elif "already" in stdout_str.lower():
                        logger.debug("node_already_in_list",
                                    target=target_node.node_id)
                        return True
                    else:
                        logger.info("node_registered_via_cli",
                                  target=target_node.node_id,
                                  output=stdout_str[:50] if stdout_str else "success")
                        return True
                else:
                    logger.warning("node_add_failed",
                                  target=target_node.node_id,
                                  exit_code=exit_code,
                                  stderr=stderr_str[:100])
                    return False
                    
            except Exception as e:
                logger.exception("node_add_exception",
                               target=target_node.node_id,
                               error=str(e))
                return False
        
        # Node1 registers ALL nodes (including itself)
        # GDB will sync node list to other nodes via established links
        registration_tasks = [register_single_node(node) for node in nodes]
        
        logger.info("starting_node_registration_from_node1", 
                   total_nodes=len(nodes))
        
        results = await asyncio.gather(*registration_tasks, return_exceptions=True)
        
        # Count successes
        success_count = sum(1 for r in results if r is True)
        failed_count = len(results) - success_count
        
        logger.info("node_registration_complete",
                   successful=success_count,
                   failed=failed_count,
                   total=len(nodes))
        
        # CRITICAL: Wait for GDB to propagate node list to ALL nodes
        # Node1 added all nodes locally, but GDB sync takes time (1-5s)
        # Without this, offline/online happens before other nodes see the list
        logger.info("waiting_for_node_list_gdb_propagation")
        
        import time
        start_wait = time.time()
        all_have_list = False
        
        while time.time() - start_wait < 30:  # Max 30s for GDB sync
            nodes_with_list = 0
            
            for node in nodes:
                try:
                    exit_code, stdout, _ = self._exec_cli(
                        node.node_id,
                        f"node list -net {self.network_name}",
                        check_output=False
                    )
                    
                    # Check if node has full list (should see len(nodes) nodes)
                    if exit_code == 0:
                        import re
                        # Count "Got N nodes:"
                        match = re.search(r'Got\s+(\d+)\s+nodes', stdout, re.IGNORECASE)
                        if match:
                            node_count = int(match.group(1))
                            if node_count >= len(nodes):
                                nodes_with_list += 1
                except Exception as e:
                    logger.debug("node_list_check_error", node=node.node_id, error=str(e)[:100])
            
            if nodes_with_list >= len(nodes):
                elapsed = time.time() - start_wait
                logger.info("all_nodes_have_node_list",
                           nodes=nodes_with_list,
                           total=len(nodes),
                           elapsed=f"{elapsed:.1f}s")
                all_have_list = True
                break
            
            # Log progress
            elapsed = time.time() - start_wait
            logger.info("node_list_propagation_progress",
                       elapsed=f"{elapsed:.1f}s",
                       nodes_with_list=nodes_with_list,
                       total=len(nodes),
                       missing=len(nodes) - nodes_with_list)
            
            await asyncio.sleep(2)
        
        if not all_have_list:
            logger.warning("node_list_gdb_sync_incomplete",
                          nodes_with_list=nodes_with_list,
                          total=len(nodes),
                          note="GDB sync requires links - will propagate after initial link establishment")
        
        # CRITICAL INSIGHT from logs:
        # GDB cluster sync requires ESTABLISHED LINKS to propagate node list
        # Chicken-and-egg: need links for GDB sync, need node list for links
        # Solution: Wait for INITIAL links (P2P discovery) → THEN offline/online to refresh
        
        logger.info("waiting_for_initial_links_before_network_reconnection")
        
        from ..monitoring.network_consensus import NetworkConsensusMonitor
        monitor = NetworkConsensusMonitor(
            nodes={f"node{n.node_id}": n for n in nodes},
            network_name=self.network_name
        )
        
        # Step 1: Wait for at least SOME links to appear (allows GDB sync to start)
        logger.info("waiting_for_at_least_one_link_per_node")
        await monitor.wait_for_links_connecting_state(timeout=90.0)
        logger.info("initial_links_established_gdb_can_sync")
        
        # Step 2: NOW do offline/online to force full mesh establishment
        # At this point: some links exist → GDB syncing → node lists propagating
        logger.info("forcing_full_mesh_reconnection_with_updated_node_lists")
        
        # First: bring all offline
        for node in nodes:
            try:
                logger.debug("bringing_offline_for_refresh", node_id=node.node_id)
                self._exec_cli(node.node_id, f"net -net {self.network_name} go offline", check_output=False)
            except Exception as e:
                logger.warning("failed_to_go_offline", node_id=node.node_id, error=str(e))
        
        # Small delay to ensure offline processed
        await asyncio.sleep(1)
        
        # Then: bring all online simultaneously → full mesh with complete node lists!
        for node in nodes:
            try:
                logger.debug("bringing_online_for_full_mesh", node_id=node.node_id)
                self._exec_cli(node.node_id, f"net -net {self.network_name} go online", check_output=False)
            except Exception as e:
                logger.warning("failed_to_go_online", node_id=node.node_id, error=str(e))
        
        logger.info("all_nodes_online_with_full_node_lists")
        
        # Step 3: Wait for FULL links establishment (all nodes active >= required)
        logger.info("waiting_for_full_links_establishment")
        await monitor.wait_for_links_established(timeout=60.0)
        logger.info("all_links_established_ready_for_consensus")
    
    # ========================================================================
    # Token Management Methods (delegated to TokenGenesisManager)
    # ========================================================================
    
    async def generate_fee_wallet(self) -> str:
        """Delegate to TokenGenesisManager."""
        return await self.token_mgr.generate_fee_wallet()
    
    async def create_native_token(self, root_cert_name: str = "pvt.stagenet.root.0") -> str:
        """Delegate to TokenGenesisManager."""
        return await self.token_mgr.create_native_token(root_cert_name)
    
    async def emit_native_token(self, fee_addr: str, root_cert_name: str = "pvt.stagenet.root.0") -> str:
        """Delegate to TokenGenesisManager."""
        return await self.token_mgr.emit_native_token(fee_addr, root_cert_name)
    
    async def create_first_transaction(
        self, 
        emission_hash: str, 
        master_nodes: List[NodeConfig] = None,
        master_cert_name: str = "pvt.stagenet.master.0"
    ) -> str:
        """Delegate to TokenGenesisManager."""
        return await self.token_mgr.create_first_transaction(emission_hash, master_nodes, master_cert_name)

    async def process_zerochain_datum(self, datum_hash: str, root_nodes: List[NodeConfig], timeout: int = 120) -> None:
        """Delegate to SyncMgr."""
        return await self.sync_mgr.process_zerochain_datum(datum_hash, root_nodes, timeout)

    async def sync_network(self, nodes: List[NodeConfig], chain_name: str = None, timeout: int = 120) -> None:
        """Delegate to SyncMgr."""
        return await self.sync_mgr.sync_network(nodes, chain_name, timeout)

    def enable_seed_mode_in_configs(self, node_ids: List[int]) -> None:
        """Delegate to GenesisConfigManager."""
        return self.config_mgr.enable_seed_mode_in_configs(node_ids)
    
    def disable_seed_mode_in_configs(self, node_ids: List[int]) -> None:
        """Delegate to GenesisConfigManager."""
        return self.config_mgr.disable_seed_mode_in_configs(node_ids)
    
    async def wait_for_first_block(self, chain_name: str, timeout: int = 60) -> None:
        """Delegate to SyncMgr."""
        return await self.sync_mgr.wait_for_first_block(chain_name, timeout)

    async def get_genesis_event_hash(self, chain_name: str) -> Optional[str]:
        """Delegate to GenesisConfigManager."""
        return await self.config_mgr.get_genesis_event_hash(chain_name)
    
    async def get_genesis_block_hash(self, chain_name: str) -> Optional[str]:
        """Delegate to GenesisConfigManager."""
        return await self.config_mgr.get_genesis_block_hash(chain_name)
    
    async def update_fee_addr_in_config(self, fee_addr: str, node_configs: List[NodeConfig]) -> None:
        """Delegate to GenesisConfigManager."""
        return await self.config_mgr.update_fee_addr_in_config(fee_addr, node_configs)
    
    async def update_static_genesis_in_config(self, chain_name: str, genesis_hash: str, node_configs: List[NodeConfig]) -> None:
        """Delegate to GenesisConfigManager."""
        return await self.config_mgr.update_static_genesis_in_config(chain_name, genesis_hash, node_configs)

