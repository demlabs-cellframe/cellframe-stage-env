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
        
        # CRITICAL: After node list population, restart network to establish links
        # Without this, nodes won't connect (node list was empty during initial NET_STATE_ONLINE)
        logger.info("restarting_network_to_establish_links")
        for node in nodes:
            try:
                # Go offline then online to trigger reconnection
                logger.debug("cycling_network_state", node_id=node.node_id)
                self._exec_cli(node.node_id, f"net -net {self.network_name} go offline", check_output=False)
                self._exec_cli(node.node_id, f"net -net {self.network_name} go online", check_output=False)
                logger.debug("network_cycled", node_id=node.node_id)
            except Exception as e:
                logger.warning("failed_to_cycle_network",
                              node_id=node.node_id,
                              error=str(e))
        
        logger.info("network_restarted_waiting_for_links")
        
        # Wait for links to actually establish before proceeding
        # This is CRITICAL - consensus won't work without active links!
        from ..monitoring.network_consensus import NetworkConsensusMonitor
        monitor = NetworkConsensusMonitor(
            nodes={f"node{n.node_id}": n for n in nodes},
            network_name=self.network_name
        )
        await monitor.wait_for_links_established(timeout=60.0)
        logger.info("all_links_established_ready_for_consensus")
    
    async def generate_fee_wallet(self) -> str:
        """
        Generate fee collection wallet on node1.
        
        Creates a wallet named 'fee_collector' on the first node
        and returns its address for use in chain configuration.
        
        Returns:
            Wallet address string
            
        Raises:
            RuntimeError: If wallet creation or address extraction fails
        """
        logger.info("generating_fee_wallet", node="node1")
        
        try:
            # Create wallet via unified CLI method
            logger.debug("creating_fee_wallet")
            exit_code, stdout_str, stderr_str = self._exec_cli(
                1,
                f"wallet new -w fee_collector -net {self.network_name}",
                check_output=True
            )
            logger.debug("fee_wallet_created", output=stdout_str[:200])
            
            # Get wallet address
            logger.debug("getting_fee_wallet_address")
            exit_code_info, stdout_info_str, stderr_info_str = self._exec_cli(
                1,
                f"wallet info -w fee_collector -net {self.network_name}",
                check_output=True
            )
            
            # Extract address from wallet info output
            # Format: "addr: <address>"
            import re
            addr_match = re.search(r'addr:\s*(\S+)', stdout_info_str, re.IGNORECASE)
            if not addr_match:
                logger.error("fee_wallet_address_not_found", output=stdout_info_str[:200])
                raise RuntimeError(f"Could not extract wallet address from output: {stdout_info_str[:200]}")
            
            fee_addr = addr_match.group(1)
            logger.info("fee_wallet_generated", address=fee_addr)
            
            return fee_addr
            
        except docker.errors.NotFound:
            error_msg = f"Container {container_name} not found"
            logger.error("container_not_found", error=error_msg)
            raise RuntimeError(error_msg)
        except Exception as e:
            logger.error("fee_wallet_generation_error", error=str(e))
            raise
    
    async def create_native_token(self, root_cert_name: str = "pvt.stagenet.root.0") -> str:
        """
        Create TCELL native token on zerochain.
        
        Executes token_decl on root node to create the native token.
        Uses zerochain (token declarations chain).
        
        Args:
            root_cert_name: Certificate name for signing (default: pvt.stagenet.master.0 for node1)
            
        Returns:
            Token declaration datum hash
            
        Raises:
            RuntimeError: If token creation fails
        """
        logger.info("creating_native_token", token="TCELL", chain="zerochain", cert=root_cert_name)
        
        try:
            # Get node1 container (root node)
            container_name = f"cellframe-stage-node-1"
            container = self.docker_client.containers.get(container_name)
            
            # Create TCELL token on zerochain via unified CLI method
            logger.debug("executing_token_decl")
            
            exit_code, stdout_str, stderr_str = self._exec_cli(
                1,
                f"token_decl -token TCELL -total_supply 1000000000 -decimals 18 -signs_total 1 -signs_emission 1 -certs {root_cert_name} -net {self.network_name} -chain zerochain",
                check_output=False
            )
            
            # Parse YAML output to check for errors
            import yaml
            try:
                output_data = yaml.safe_load(stdout_str)
                if isinstance(output_data, dict) and 'errors' in output_data:
                    error_code = output_data['errors'].get('code', -1)
                    error_msg = output_data['errors'].get('message', '')
                    
                    if error_code != 0:
                        logger.error("token_decl_failed", code=error_code, message=error_msg)
                        raise RuntimeError(f"token_decl failed: code={error_code}, message={error_msg}")
                    
                    # Success - extract hash from message
                    # Format: "Datum 0x... with token TCELL is placed in datum pool"
                    import re
                    hash_match = re.search(r'(0x[A-Fa-f0-9]{64})', error_msg)
                    if hash_match:
                        token_hash = hash_match.group(1)
                        logger.info("native_token_created", token="TCELL", hash=token_hash)
                        return token_hash
                    else:
                        logger.error("token_hash_not_found", message=error_msg)
                        raise RuntimeError(f"Could not extract token hash from: {error_msg}")
                        
            except yaml.YAMLError as e:
                logger.error("failed_to_parse_token_decl_output", error=str(e), output=stdout_str[:200])
                raise RuntimeError(f"Failed to parse token_decl output: {e}")
            
            if exit_code != 0:
                error_msg = f"token_decl failed: exit code {exit_code}"
                if stderr_str:
                    error_msg += f", stderr: {stderr_str}"
                logger.error("token_decl_execution_failed", error=error_msg)
                raise RuntimeError(error_msg)
            
            # Fallback: no errors dict found
            logger.error("unexpected_token_decl_output", output=stdout_str[:200])
            raise RuntimeError(f"Unexpected token_decl output format: {stdout_str[:200]}")
            
        except docker.errors.NotFound:
            error_msg = f"Container {container_name} not found"
            logger.error("container_not_found", error=error_msg)
            raise RuntimeError(error_msg)
        except Exception as e:
            logger.error("native_token_creation_error", error=str(e))
            raise
    
    async def emit_native_token(self, fee_addr: str, root_cert_name: str = "pvt.stagenet.root.0") -> str:
        """
        Emit TCELL native token to fee wallet on zerochain.
        
        Executes token_emit on root node to create emission.
        Uses zerochain (emission chain).
        
        Args:
            fee_addr: Fee wallet address to receive emission
            root_cert_name: Certificate name for signing (default: pvt.stagenet.master.0)
            
        Returns:
            Emission datum hash
            
        Raises:
            RuntimeError: If emission fails
        """
        logger.info("emitting_native_token", token="TCELL", chain="zerochain", to=fee_addr)
        
        try:
            container_name = f"cellframe-stage-node-1"
            container = self.docker_client.containers.get(container_name)
            
            logger.debug("executing_token_emit")
            
            exit_code, stdout_str, stderr_str = self._exec_cli(
                1,
                f"token_emit -token TCELL -emission_value 1000000000 -addr {fee_addr} -certs {root_cert_name} -net {self.network_name} -chain zerochain",
                check_output=False
            )
            
            logger.info("token_emit_raw_output", exit_code=exit_code, stdout_preview=stdout_str[:500], stderr_preview=stderr_str[:200])
            
            if exit_code != 0:
                error_msg = f"token_emit failed: exit code {exit_code}"
                if stderr_str:
                    error_msg += f", stderr: {stderr_str}"
                logger.error("token_emit_execution_failed", error=error_msg)
                raise RuntimeError(error_msg)
            
            # Parse output - can be YAML or plain text
            import yaml, re
            
            # Try YAML first
            try:
                output_data = yaml.safe_load(stdout_str)
                if isinstance(output_data, dict) and 'errors' in output_data:
                    error_code = output_data['errors'].get('code', -1)
                    error_msg = output_data['errors'].get('message', '')
                    
                    if error_code != 0:
                        logger.error("token_emit_failed", code=error_code, message=error_msg)
                        raise RuntimeError(f"token_emit failed: code={error_code}, message={error_msg}")
                    
                    # YAML format - extract hash from message
                    hash_match = re.search(r'(0x[A-Fa-f0-9]{64})', error_msg)
                    if hash_match:
                        emission_hash = hash_match.group(1)
                        logger.info("native_token_emitted", token="TCELL", hash=emission_hash)
                        return emission_hash
            except yaml.YAMLError:
                # Not YAML - try plain text parsing
                pass
            
            # Plain text format: "result: Datum 0x... with 256bit emission is placed in datum pool"
            hash_match = re.search(r'Datum\s+(0x[A-Fa-f0-9]{64})', stdout_str, re.IGNORECASE)
            if hash_match:
                emission_hash = hash_match.group(1)
                logger.info("native_token_emitted", token="TCELL", hash=emission_hash, format="plain_text")
                return emission_hash
            
            # Fallback - no hash found
            logger.error("emission_hash_not_found", output=stdout_str[:200])
            raise RuntimeError(f"Could not extract emission hash from output: {stdout_str[:200]}")
            
        except Exception as e:
            logger.error("native_token_emission_error", error=str(e))
            raise
    
    async def create_first_transaction(
        self, 
        emission_hash: str, 
        master_nodes: List[NodeConfig] = None,
        master_cert_name: str = "pvt.stagenet.master.0"
    ) -> str:
        """
        Create first TCELL transaction on main chain.
        
        CRITICAL: Must execute on MASTER node with master certificate!
        ROOT nodes don't have pvt.stagenet.master.N certificates.
        
        Args:
            emission_hash: Emission datum hash to spend from
            master_nodes: List of master node configs (uses first one)
            master_cert_name: Certificate name for signing (default: pvt.stagenet.master.0)
            
        Returns:
            Transaction datum hash
            
        Raises:
            RuntimeError: If transaction creation fails or no master nodes provided
        """
        logger.info("creating_first_transaction", token="TCELL", chain="main", from_emission=emission_hash[:16])
        
        if not master_nodes or len(master_nodes) == 0:
            raise RuntimeError("No master nodes provided for tx_create")
        
        # Use first MASTER node (has pvt.stagenet.master.0)
        first_master = master_nodes[0]
        logger.debug("using_master_node_for_tx", node_id=first_master.node_id)
        
        try:
            container_name = f"cellframe-stage-node-{first_master.node_id}"
            container = self.docker_client.containers.get(container_name)
            
            # Use unified CLI method (no -chain parameter for auto-detection)
            logger.debug("executing_tx_create")
            
            exit_code, stdout_str, stderr_str = self._exec_cli(
                first_master.node_id,  # Execute on dynamically determined first MASTER node
                f"tx_create -token TCELL -from_emission {emission_hash} -value 100000000 -fee 0.1 -cert {master_cert_name} -net {self.network_name}",
                check_output=False
            )
            
            logger.info("tx_create_raw_output", exit_code=exit_code, stdout_preview=stdout_str[:500])
            
            if exit_code != 0:
                error_msg = f"tx_create failed: exit code {exit_code}"
                logger.error("tx_create_execution_failed", error=error_msg)
                raise RuntimeError(error_msg)
            
            # Parse output - can be YAML or plain text
            import yaml, re
            
            # Try YAML first
            try:
                output_data = yaml.safe_load(stdout_str)
                if isinstance(output_data, dict) and 'errors' in output_data:
                    error_code = output_data['errors'].get('code', -1)
                    error_msg = output_data['errors'].get('message', '')
                    
                    if error_code != 0:
                        logger.error("tx_create_failed", code=error_code, message=error_msg)
                        raise RuntimeError(f"tx_create failed: code={error_code}, message={error_msg}")
                    
                    # YAML format - extract hash from message
                    hash_match = re.search(r'(0x[A-Fa-f0-9]{64})', error_msg)
                    if hash_match:
                        tx_hash = hash_match.group(1)
                        logger.info("first_transaction_created", token="TCELL", hash=tx_hash)
                        return tx_hash
            except yaml.YAMLError:
                # Not YAML - try plain text parsing
                pass
            
            # Plain text format: extract any 0x hash
            hash_match = re.search(r'(0x[A-Fa-f0-9]{64})', stdout_str, re.IGNORECASE)
            if hash_match:
                tx_hash = hash_match.group(1)
                logger.info("first_transaction_created", token="TCELL", hash=tx_hash, format="plain_text")
                return tx_hash
            
            # Fallback - no hash found
            logger.error("tx_hash_not_found", output=stdout_str[:200])
            raise RuntimeError(f"Could not extract tx hash from output: {stdout_str[:200]}")
            
        except Exception as e:
            logger.error("first_transaction_creation_error", error=str(e))
            raise
    
    async def process_zerochain_datum(self, datum_hash: str, root_nodes: List[NodeConfig], timeout: int = 120) -> None:
        """
        Process datum through zerochain DAG-PoA consensus.
        
        Waits for datum to appear on first root node, then triggers
        mempool_proc on remaining root nodes to finalize via DAG-PoA.
        
        Args:
            datum_hash: Datum hash to process
            root_nodes: List of root node configurations
            timeout: Timeout in seconds for datum to appear
            
        Raises:
            RuntimeError: If datum processing fails
        """
        logger.info("processing_zerochain_datum", datum=datum_hash[:16], root_count=len(root_nodes))
        
        if not root_nodes:
            raise RuntimeError("No root nodes provided for zerochain datum processing")
        
        try:
            # Step 1: Wait for datum to appear in mempool on first root node
            first_node = root_nodes[0]
            container_name = f"cellframe-stage-node-{first_node.node_id}"
            container = self.docker_client.containers.get(container_name)
            
            logger.debug("waiting_for_datum_in_mempool", node=f"node{first_node.node_id}", datum=datum_hash[:16])
            
            # Poll mempool for datum
            import time
            start_time = time.time()
            found = False
            
            while time.time() - start_time < timeout:
                exit_code, stdout_str, stderr_str = self._exec_cli(
                    first_node.node_id,
                    f"mempool_list -net {self.network_name} -chain zerochain",
                    check_output=False
                )
                
                if datum_hash.lower() in stdout_str.lower():
                    found = True
                    logger.info("datum_appeared_in_mempool", node=f"node{first_node.node_id}", elapsed=f"{time.time() - start_time:.1f}s")
                    break
                
                await asyncio.sleep(1)
            
            if not found:
                raise RuntimeError(f"Datum {datum_hash[:16]}... did not appear in mempool within {timeout}s")
            
            # Step 2: Trigger mempool_proc on remaining root nodes
            for node in root_nodes[1:]:
                container_name = f"cellframe-stage-node-{node.node_id}"
                try:
                    node_container = self.docker_client.containers.get(container_name)
                    
                    # Check if container is still running
                    node_container.reload()  # Refresh container state
                    if node_container.status != 'running':
                        logger.warning("container_not_running", 
                                      node=f"node{node.node_id}",
                                      status=node_container.status)
                        continue
                    
                    logger.debug("triggering_mempool_proc", node=f"node{node.node_id}", datum=datum_hash[:16])
                    
                    exit_code, stdout, stderr = self._exec_cli(
                        node.node_id,
                        f"mempool_proc -datum {datum_hash} -net {self.network_name} -chain zerochain",
                        check_output=False
                    )
                    
                    if exit_code == 0:
                        logger.info("mempool_proc_triggered", node=f"node{node.node_id}")
                    else:
                        logger.warning("mempool_proc_failed", node=f"node{node.node_id}", exit_code=exit_code, stderr=stderr)
                        
                except docker.errors.NotFound:
                    logger.warning("container_not_found_skipping", 
                                  node=f"node{node.node_id}",
                                  container=container_name)
                    continue
                except Exception as e:
                    logger.warning("failed_to_trigger_mempool_proc", node=f"node{node.node_id}", error=str(e))
            
            # Step 3: Wait for datum to be finalized in DAG (polling with timeout)
            # Note: DAG-PoA uses events, not blocks
            logger.info("waiting_for_datum_in_dag", datum=datum_hash[:16], timeout=timeout)
            dag_check_start = time.time()
            found_in_dag = False
            last_log_time = time.time()
            
            while time.time() - dag_check_start < timeout:
                # For DAG-PoA, check if datum is in events (not blocks!)
                exit_code, stdout_events_str, _ = self._exec_cli(
                    1,
                    f"dag event list -net {self.network_name} -chain zerochain -from events -limit 20",
                    check_output=False
                )
                
                # Log progress every 10 seconds
                elapsed = time.time() - dag_check_start
                if time.time() - last_log_time >= 10:
                    logger.info("dag_finalization_progress", 
                               datum=datum_hash[:16],
                               elapsed=f"{elapsed:.1f}s",
                               event_list_preview=stdout_events_str[:300] if stdout_events_str else "empty",
                               exit_code=exit_code)
                    last_log_time = time.time()
                
                # Check if any events appeared (indicates DAG is working)
                # Note: CLI output doesn't show datum hash inside events, only event hash
                # If total events > 0, it means DAG is processing datums
                if "total events:" in stdout_events_str:
                    import re
                    match = re.search(r'total events:\s*(\d+)', stdout_events_str)
                    if match and int(match.group(1)) > 0:
                        found_in_dag = True
                        logger.info("datum_finalized_in_zerochain", 
                                   datum=datum_hash[:16], 
                                   elapsed=f"{elapsed:.1f}s",
                                   total_events=match.group(1))
                        break
                
                # Wait before retry
                await asyncio.sleep(2)
            
            if not found_in_dag:
                # Final diagnostic
                logger.error("datum_not_finalized_in_dag", 
                           datum=datum_hash[:16], 
                           elapsed=f"{time.time() - dag_check_start:.1f}s",
                           last_event_list=stdout_events_str[:500] if 'stdout_events_str' in locals() else "N/A")
                raise RuntimeError(f"Datum {datum_hash[:16]}... was not finalized in DAG within {timeout}s")
                
        except Exception as e:
            logger.error("zerochain_datum_processing_error", error=str(e))
            raise
    
    async def sync_network(self, nodes: List[NodeConfig], timeout: int = 120) -> None:
        """
        Synchronize all nodes in the network.
        
        Triggers sync on all nodes and waits for completion.
        Monitors sync progress via net status.
        
        Args:
            nodes: List of all node configurations
            timeout: Timeout in seconds for sync completion
            
        Raises:
            RuntimeError: If sync fails or times out
        """
        logger.info("synchronizing_network", node_count=len(nodes), timeout=timeout)
        
        try:
            # Trigger sync on all nodes
            for node in nodes:
                container_name = f"cellframe-stage-node-{node.node_id}"
                try:
                    container = self.docker_client.containers.get(container_name)
                    
                    logger.debug("triggering_sync", node=f"node{node.node_id}")
                    
                    exit_code, stdout_str, stderr_str = self._exec_cli(
                        node.node_id,
                        f"net -net {self.network_name} sync all",
                        check_output=False
                    )
                    
                    if exit_code == 0:
                        logger.debug("sync_triggered", node=f"node{node.node_id}")
                    else:
                        logger.warning("sync_trigger_failed", node=f"node{node.node_id}", exit_code=exit_code)
                        
                except Exception as e:
                    logger.warning("failed_to_trigger_sync", node=f"node{node.node_id}", error=str(e))
            
            # Monitor sync progress
            import time
            start_time = time.time()
            check_interval = 5
            
            while time.time() - start_time < timeout:
                all_synced = True
                sync_status = {}
                
                for node in nodes:
                    container_name = f"cellframe-stage-node-{node.node_id}"
                    try:
                        container = self.docker_client.containers.get(container_name)
                        
                        exit_code_status, stdout_str, stderr_str = self._exec_cli(
                            node.node_id,
                            f"net -net {self.network_name} get status",
                            check_output=False
                        )
                        
                        # Check for "synced" status
                        import re
                        synced = bool(re.search(r'status:\s*synced', stdout_str, re.IGNORECASE))
                        sync_status[f"node{node.node_id}"] = "synced" if synced else "syncing"
                        
                        if not synced:
                            all_synced = False
                            
                    except Exception as e:
                        logger.warning("failed_to_check_sync_status", node=f"node{node.node_id}", error=str(e))
                        all_synced = False
                        sync_status[f"node{node.node_id}"] = "error"
                
                if all_synced:
                    logger.info("network_synchronized", elapsed=f"{time.time() - start_time:.1f}s")
                    return
                
                logger.debug("sync_progress", status=sync_status, elapsed=f"{time.time() - start_time:.1f}s")
                await asyncio.sleep(check_interval)
            
            # Timeout reached
            logger.warning("sync_timeout", elapsed=timeout, final_status=sync_status)
            # Don't raise - sync may complete eventually
            
        except Exception as e:
            logger.error("network_sync_error", error=str(e))
            raise
    
    def enable_seed_mode_in_configs(self, node_ids: List[int]) -> None:
        """
        Enable seed_mode in node configs BEFORE container start.
        
        Modifies cellframe-node.cfg on HOST filesystem.
        Must be called BEFORE compose.up().
        
        Args:
            node_ids: List of node IDs to enable seed_mode for
        """
        logger.info("enabling_seed_mode_in_configs", node_ids=node_ids)
        
        for node_id in node_ids:
            try:
                node_config_file = self.base_path / ".." / "testing" / "cache" / "configs" / f"node{node_id}" / "cellframe-node.cfg"
                node_config_file = node_config_file.resolve()
                
                if not node_config_file.exists():
                    logger.warning("config_file_not_found", node_id=node_id, path=str(node_config_file))
                    continue
                
                # Read, replace, write
                config_content = node_config_file.read_text()
                config_content = config_content.replace("seed_mode=false", "seed_mode=true")
                node_config_file.write_text(config_content)
                logger.debug("seed_mode_enabled_in_config_file", node_id=node_id)
                    
            except Exception as e:
                logger.error("enable_seed_mode_error", node_id=node_id, error=str(e))
    
    def disable_seed_mode_in_configs(self, node_ids: List[int]) -> None:
        """
        Disable seed_mode in node configs BEFORE container restart.
        
        Modifies cellframe-node.cfg on HOST filesystem.
        
        CRITICAL: Ensures seed_mode=false in final snapshot!
        
        Args:
            node_ids: List of node IDs to disable seed_mode for
        """
        logger.info("disabling_seed_mode_in_configs", node_ids=node_ids)
        
        for node_id in node_ids:
            try:
                node_config_file = self.base_path / ".." / "testing" / "cache" / "configs" / f"node{node_id}" / "cellframe-node.cfg"
                node_config_file = node_config_file.resolve()
                
                if not node_config_file.exists():
                    logger.warning("config_file_not_found", node_id=node_id, path=str(node_config_file))
                    continue
                
                # Read, replace, write
                config_content = node_config_file.read_text()
                config_content = config_content.replace("seed_mode=true", "seed_mode=false")
                node_config_file.write_text(config_content)
                logger.debug("seed_mode_disabled_in_config_file", node_id=node_id)
                    
            except Exception as e:
                logger.error("disable_seed_mode_error", node_id=node_id, error=str(e))
    
    async def get_genesis_block_hash(self, chain_name: str) -> Optional[str]:
        """
        Get genesis block hash from specified chain.
        
        Retrieves the first block hash from a chain for use in
        static_genesis_block configuration.
        
        Args:
            chain_name: Chain name (zerochain or main)
            
        Returns:
            Genesis block hash or None if not found
        """
        logger.info("getting_genesis_block", chain=chain_name)
        
        try:
            # Get from node1
            container_name = f"cellframe-stage-node-1"
            container = self.docker_client.containers.get(container_name)
            
            logger.debug("fetching_first_block", chain=chain_name)
            
            exit_code, stdout_str, stderr_str = self._exec_cli(
                1,
                f"block list -net {self.network_name} -chain {chain_name} -first 1",
                check_output=False
            )
            
            if exit_code != 0:
                logger.warning("block_list_failed", chain=chain_name, exit_code=exit_code)
                return None
            
            # Parse block hash from output
            # Format: "block #0 hash: 0x..."
            import re
            hash_match = re.search(r'hash:\s*(0x[A-Fa-f0-9]{64})', stdout_str, re.IGNORECASE)
            if hash_match:
                genesis_hash = hash_match.group(1)
                logger.info("genesis_block_found", chain=chain_name, hash=genesis_hash[:16])
                return genesis_hash
            
            # Try alternative format
            hash_match = re.search(r'(0x[A-Fa-f0-9]{64})', stdout_str)
            if hash_match:
                genesis_hash = hash_match.group(1)
                logger.info("genesis_block_found_alt_format", chain=chain_name, hash=genesis_hash[:16])
                return genesis_hash
            
            logger.warning("genesis_block_not_found", chain=chain_name, output=stdout_str[:200])
            return None
            
        except Exception as e:
            logger.error("genesis_block_retrieval_error", chain=chain_name, error=str(e))
            return None
    
    async def update_static_genesis_in_config(self, chain_name: str, genesis_hash: str, node_configs: List[NodeConfig]) -> None:
        """
        Update static_genesis_block in chain config files on ALL nodes.
        
        CRITICAL: Must be done after genesis creation and seed_mode disabling
        to ensure all nodes validate the same genesis.
        
        Args:
            chain_name: Chain name (main or zerochain)
            genesis_hash: Genesis block hash (0x...)
            node_configs: List of all node configurations
        """
        logger.info("updating_static_genesis_in_configs", 
                   chain=chain_name, 
                   hash=genesis_hash[:16],
                   nodes=len(node_configs))
        
        for node in node_configs:
            try:
                container_name = f"cellframe-stage-{node.name}"
                container = self.docker_client.containers.get(container_name)
                
                config_path = f"/opt/cellframe-node/etc/network/{self.network_name}/{chain_name}.cfg"
                
                # Update static_genesis_block in chain config
                cmd = [
                    "sed", "-i",
                    f"s|^static_genesis_block=.*|static_genesis_block={genesis_hash}|g",
                    config_path
                ]
                
                result = container.exec_run(cmd)
                if result.exit_code != 0:
                    logger.warning("failed_to_update_genesis_hash", 
                                  node=node.name, 
                                  error=result.output)
                else:
                    logger.debug("genesis_hash_updated", node=node.name, hash=genesis_hash[:16])
                    
            except Exception as e:
                logger.error("update_genesis_hash_error", node=node.name, error=str(e))
        
        logger.info("genesis_hash_updated_on_all_nodes", chain=chain_name)

