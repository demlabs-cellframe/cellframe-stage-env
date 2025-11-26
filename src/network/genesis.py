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

from src.utils.logger import get_logger
from .models import NodeConfig
from .genesis_base import BaseGenesisManager
from .genesis_config import GenesisConfigManager
from .genesis_token import TokenGenesisManager
from .genesis_sync import ChainSyncManager
from .genesis_registration import NodeRegistrationManager
from .genesis_validator import ValidatorManager

logger = get_logger(__name__)


class GenesisInitializer(BaseGenesisManager):
    """
    Initialize genesis state for stagenet.
    
    Orchestrates genesis initialization by delegating to specialized managers.
    
    Inherits from BaseGenesisManager:
    - _exec_cli(): CLI command execution
    - _read_node_addr_with_retry(): Node address retrieval
    """
    
    def __init__(self, base_path: Path, network_name: str = "stagenet", config_path: Path = None):
        """
        Initialize genesis initializer.
        
        Args:
            base_path: Base path to stage-env directory
            network_name: Network name (default: stagenet)
            config_path: Optional path to config file
        """
        super().__init__(base_path, network_name, config_path)
        
        # Load cache dir from config
        from ..config.manager import get_config_loader
        config_loader = get_config_loader()
        paths_config = config_loader.get_paths_config()
        cache_dir_relative = paths_config.get('cache_dir', 'cache')
        # Resolve cache dir relative to BASE_PATH (always)
        self.certs_cache = (base_path / cache_dir_relative / "certs").resolve()
        
        self.cli_config_path = "/opt/cellframe-node/etc/cellframe-node.cfg"
        
        # Initialize specialized managers for modular architecture (pass config_path!)
        self.config_mgr = GenesisConfigManager(base_path, network_name, config_path)
        self.token_mgr = TokenGenesisManager(base_path, network_name, config_path)
        self.sync_mgr = ChainSyncManager(base_path, network_name, config_path)
        self.registration_mgr = NodeRegistrationManager(base_path, network_name, config_path, self.certs_cache)
        self.validator_mgr = ValidatorManager(base_path, network_name, config_path)
        
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
    
