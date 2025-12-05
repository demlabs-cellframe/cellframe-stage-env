"""
Docker container IP address waiter.

Waits for Docker containers to receive IP addresses from Docker networks.
"""

import time
from typing import List, Optional
import docker
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DockerIPWaiter:
    """Wait for Docker containers to receive IP addresses."""
    
    def __init__(self, docker_client: docker.DockerClient):
        """
        Initialize Docker IP waiter.
        
        Args:
            docker_client: Docker client instance
        """
        self.docker_client = docker_client
        self._container_ips = {}  # Cache resolved IPs
    
    def wait_for_container_ips(
        self,
        container_names: List[str],
        timeout: float = 30.0,
        check_interval: float = 0.5
    ) -> bool:
        """
        Wait for containers to receive IP addresses.
        
        Args:
            container_names: List of container names to check
            timeout: Maximum wait time in seconds
            check_interval: Time between checks in seconds
            
        Returns:
            True if all containers have IPs, False on timeout
            
        Raises:
            docker.errors.NotFound: If container doesn't exist
        """
        start_time = time.time()
        pending = set(container_names)
        
        logger.info("waiting_for_container_ips", 
                   containers=list(pending),
                   timeout=timeout)
        
        while pending and (time.time() - start_time) < timeout:
            for container_name in list(pending):
                try:
                    container = self.docker_client.containers.get(container_name)
                    
                    # Get IP from any connected network
                    networks = container.attrs['NetworkSettings']['Networks']
                    ip_address = next(
                        (net['IPAddress'] for net in networks.values() 
                         if net.get('IPAddress')),
                        None
                    )
                    
                    if ip_address:
                        self._container_ips[container_name] = ip_address
                        pending.remove(container_name)
                        logger.debug("container_ip_acquired",
                                   container=container_name,
                                   ip=ip_address)
                except docker.errors.NotFound:
                    # Container might not be created yet (race condition with docker-compose up)
                    # Log warning but continue retrying until timeout
                    logger.debug("container_not_found_retrying", container=container_name)
                    # Do not raise - allow retry loop to continue
                    pass
                except Exception as e:
                    logger.debug("container_ip_check_error",
                               container=container_name,
                               error=str(e))
            
            if pending:
                time.sleep(check_interval)
        
        if not pending:
            logger.info("all_containers_have_ips",
                       count=len(container_names),
                       elapsed=round(time.time() - start_time, 1))
            return True
        else:
            logger.warning("ip_acquisition_timeout",
                         pending=list(pending),
                         elapsed=round(time.time() - start_time, 1))
            return False
    
    def get_container_ip(self, container_name: str) -> str:
        """
        Get cached container IP address.
        
        Args:
            container_name: Container name
            
        Returns:
            IP address string
            
        Raises:
            RuntimeError: If IP not found in cache
        """
        if container_name not in self._container_ips:
            raise RuntimeError(
                f"IP address for container '{container_name}' not found in cache. "
                f"Did you call wait_for_container_ips() first?"
            )
        return self._container_ips[container_name]
    
    def clear_cache(self):
        """Clear IP address cache."""
        self._container_ips.clear()

