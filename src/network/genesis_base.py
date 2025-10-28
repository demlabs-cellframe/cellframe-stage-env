"""
Base class for genesis managers.

Provides common functionality for all genesis-related managers.
"""

import re
import time
from pathlib import Path

import docker

from ..utils.logger import get_logger


logger = get_logger(__name__)


class BaseGenesisManager:
    """
    Base class for all genesis managers.
    
    Provides common functionality:
    - CLI command execution in containers
    - Node address retrieval with retry logic
    - Docker client management
    """
    
    def __init__(self, base_path: Path, network_name: str = "stagenet"):
        """
        Initialize base genesis manager.
        
        Args:
            base_path: Base path to stage-env directory
            network_name: Network name (default: stagenet)
        """
        self.base_path = base_path
        self.network_name = network_name
        self.docker_client = docker.from_env()
    
    def _exec_cli(self, node_id: int, command: str, check_output: bool = True) -> tuple:
        """
        Execute CLI command inside container.
        
        Args:
            node_id: Node ID (1-8)
            command: CLI command without 'cellframe-node-cli' prefix
            check_output: Whether to check for errors in output
            
        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        container_name = f"cellframe-stage-node-{node_id}"
        try:
            container = self.docker_client.containers.get(container_name)
            
            # Execute command inside container
            exit_code, output = container.exec_run(
                f"cellframe-node-cli {command}",
                demux=True
            )
            
            # Demux separates stdout and stderr
            stdout_bytes, stderr_bytes = output if isinstance(output, tuple) else (output, b"")
            stdout_str = stdout_bytes.decode('utf-8') if stdout_bytes else ""
            stderr_str = stderr_bytes.decode('utf-8') if stderr_bytes else ""
            
            return exit_code, stdout_str, stderr_str
            
        except docker.errors.NotFound:
            logger.error("container_not_found", container=container_name)
            return 1, "", f"Container {container_name} not found"
        except Exception as e:
            logger.error("cli_exec_error", container=container_name, error=str(e))
            return 1, "", str(e)
    
    def _read_node_addr_from_cli(self, node_id: int, max_retries: int = 3) -> str:
        """
        Read node address from running container via CLI with retry logic.
        
        Executes 'node dump -net {network}' and parses node address from output.
        
        Args:
            node_id: Node ID (1-8)
            max_retries: Maximum number of retry attempts
            
        Returns:
            Node address string or empty string if failed
        """
        for attempt in range(max_retries):
            try:
                exit_code, stdout_str, stderr_str = self._exec_cli(
                    node_id,
                    f"node dump -net {self.network_name}",
                    check_output=False
                )
                
                if exit_code == 0 and stdout_str:
                    # Parse node address from output
                    # Format: "Node addr: XXXX::YYYY::ZZZZ::WWWW"
                    addr_match = re.search(r'Node addr:\s*([A-Fa-f0-9:]+)', stdout_str)
                    if addr_match:
                        node_addr = addr_match.group(1)
                        logger.debug("node_addr_found",
                                   node_id=node_id,
                                   addr=node_addr,
                                   attempt=attempt + 1)
                        return node_addr
                    else:
                        logger.warning("node_addr_not_in_output",
                                     node_id=node_id,
                                     attempt=attempt + 1,
                                     output_preview=stdout_str[:200])
                else:
                    logger.warning("node_dump_failed",
                                 node_id=node_id,
                                 attempt=attempt + 1,
                                 exit_code=exit_code,
                                 stderr=stderr_str[:200])
                
            except Exception as e:
                logger.warning("node_addr_read_exception",
                             node_id=node_id,
                             attempt=attempt + 1,
                             error=str(e))
            
            # Wait before retry
            if attempt < max_retries - 1:
                time.sleep(2)
        
        logger.error("failed_to_read_node_addr_after_retries",
                   node_id=node_id,
                   max_retries=max_retries)
        return ""

