"""
Docker Compose management using Docker SDK.

Modern replacement for deprecated docker-compose library.
Uses docker SDK 7.0+ with native compose v2 support.
"""

import time
from pathlib import Path
from typing import Dict, List, Optional

import docker
from docker.errors import DockerException, NotFound
from docker.models.containers import Container

from ..utils.logger import get_logger

logger = get_logger(__name__)


class DockerComposeManager:
    """Manage Docker Compose services using Docker SDK."""
    
    def __init__(self, project_dir: Path, project_name: str = "cellframe"):
        """
        Initialize Docker Compose manager.
        
        Args:
            project_dir: Project directory containing docker-compose.yml
            project_name: Docker Compose project name
        """
        self.project_dir = project_dir
        self.project_name = project_name
        self.compose_file = project_dir / "docker-compose.yml"
        
        try:
            self.client = docker.from_env()
            logger.info("docker_connected", version=self.client.version()["Version"])
        except DockerException as e:
            logger.error("docker_connection_failed", error=str(e))
            raise
    
    def build(
        self,
        services: Optional[List[str]] = None,
        no_cache: bool = False,
    ) -> None:
        """
        Build Docker images.
        
        Args:
            services: List of service names to build (None = all)
            no_cache: Don't use cache
        """
        logger.info("building_images", 
                   services=services or "all",
                   no_cache=no_cache)
        
        # Use docker compose CLI via subprocess for build
        # (docker SDK doesn't have direct compose build API yet)
        from ..utils.cli import run_command
        
        cmd = ["docker", "compose", "-f", str(self.compose_file),
               "-p", self.project_name, "build"]
        
        if no_cache:
            cmd.append("--no-cache")
        
        if services:
            cmd.extend(services)
        
        run_command(cmd, cwd=self.project_dir)
        logger.info("build_completed")
    
    def cleanup_stale_resources(self) -> None:
        """
        Clean up stale containers and networks from previous runs.
        
        This prevents "network overlap" and "container name conflict" errors.
        """
        logger.info("cleanup_stale_resources", project=self.project_name)
        
        # Find and remove stale containers with this project name
        try:
            stale_containers = self.client.containers.list(
                all=True,
                filters={"label": f"com.docker.compose.project={self.project_name}"}
            )
            
            if stale_containers:
                logger.info("removing_stale_containers", count=len(stale_containers))
                for container in stale_containers:
                    try:
                        logger.debug("removing_container", 
                                   name=container.name,
                                   id=container.short_id)
                        container.remove(force=True)
                    except Exception as e:
                        logger.warning("failed_to_remove_container",
                                     name=container.name,
                                     error=str(e))
            else:
                logger.debug("no_stale_containers")
        except Exception as e:
            logger.warning("failed_to_list_containers", error=str(e))
        
        # Find and remove stale networks with this project name
        try:
            all_networks = self.client.networks.list()
            stale_networks = [
                net for net in all_networks
                if self.project_name in net.name
            ]
            
            if stale_networks:
                logger.info("removing_stale_networks", count=len(stale_networks))
                for network in stale_networks:
                    try:
                        logger.debug("removing_network",
                                   name=network.name,
                                   id=network.short_id)
                        network.remove()
                    except Exception as e:
                        logger.warning("failed_to_remove_network",
                                     name=network.name,
                                     error=str(e))
            else:
                logger.debug("no_stale_networks")
        except Exception as e:
            logger.warning("failed_to_list_networks", error=str(e))
        
        logger.info("cleanup_completed")
    
    def up(
        self,
        services: Optional[List[str]] = None,
        detach: bool = True,
        wait: bool = True,
    ) -> None:
        """
        Start services.
        
        Args:
            services: List of service names (None = all)
            detach: Run in background
            wait: Wait for services to be ready
        """
        logger.info("starting_services", services=services or "all")
        
        from ..utils.cli import run_command
        
        cmd = ["docker", "compose", "-f", str(self.compose_file),
               "-p", self.project_name, "up"]
        
        if detach:
            cmd.append("-d")
        
        if services:
            cmd.extend(services)
        
        run_command(cmd, cwd=self.project_dir)
        
        if wait:
            self.wait_for_services(services)
        
        logger.info("services_started")
    
    def down(self, volumes: bool = False, remove_images: bool = False) -> None:
        """
        Stop and remove services.
        
        Args:
            volumes: Remove volumes
            remove_images: Remove images
        """
        logger.info("stopping_services", volumes=volumes, remove_images=remove_images)
        
        from ..utils.cli import run_command
        
        cmd = ["docker", "compose", "-f", str(self.compose_file),
               "-p", self.project_name, "down"]
        
        if volumes:
            cmd.append("-v")
        
        if remove_images:
            cmd.extend(["--rmi", "all"])
        
        run_command(cmd, cwd=self.project_dir)
        logger.info("services_stopped")
    
    def ps(self) -> List[Container]:
        """
        List running containers for this project.
        
        Returns:
            List of Container objects
        """
        filters = {"label": f"com.docker.compose.project={self.project_name}"}
        containers = self.client.containers.list(filters=filters, all=True)
        
        logger.debug("containers_listed", count=len(containers))
        return containers
    
    def logs(
        self,
        service: str,
        follow: bool = False,
        tail: int = 100,
    ) -> str:
        """
        Get logs for a service.
        
        Args:
            service: Service name
            follow: Follow log output
            tail: Number of lines from end
            
        Returns:
            Log output as string
        """
        containers = self.ps()
        
        for container in containers:
            labels = container.labels
            if labels.get("com.docker.compose.service") == service:
                logger.debug("fetching_logs", service=service, tail=tail)
                
                if follow:
                    # For follow, return generator
                    return container.logs(stream=True, follow=True, tail=tail)
                else:
                    return container.logs(tail=tail).decode("utf-8")
        
        raise NotFound(f"Service '{service}' not found")
    
    def exec(
        self,
        service: str,
        command: List[str],
    ) -> tuple[int, str]:
        """
        Execute command in service container.
        
        Args:
            service: Service name
            command: Command to execute
            
        Returns:
            Tuple of (exit_code, output)
        """
        containers = self.ps()
        
        for container in containers:
            labels = container.labels
            if labels.get("com.docker.compose.service") == service:
                logger.debug("executing_command", 
                           service=service,
                           command=" ".join(command))
                
                result = container.exec_run(command)
                return result.exit_code, result.output.decode("utf-8")
        
        raise NotFound(f"Service '{service}' not found")
    
    def wait_for_services(
        self,
        services: Optional[List[str]] = None,
        timeout: int = 300,
    ) -> None:
        """
        Wait for services to be healthy.
        
        Args:
            services: List of service names (None = all)
            timeout: Timeout in seconds
        """
        logger.info("waiting_for_services", timeout=timeout)
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            containers = self.ps()
            
            if not containers:
                time.sleep(2)
                continue
            
            all_healthy = True
            
            for container in containers:
                # Check if this is one of our target services
                service_name = container.labels.get("com.docker.compose.service")
                
                if services and service_name not in services:
                    continue
                
                # Check health status
                if container.status != "running":
                    all_healthy = False
                    break
                
                # If container has health check, verify it
                health = container.attrs.get("State", {}).get("Health", {})
                if health and health.get("Status") != "healthy":
                    all_healthy = False
                    break
            
            if all_healthy and containers:
                logger.info("services_ready")
                return
            
            time.sleep(2)
        
        raise TimeoutError(f"Services not ready after {timeout}s")
    
    def get_service_status(self) -> Dict[str, str]:
        """
        Get status of all services.
        
        Returns:
            Dict mapping service name to status
        """
        containers = self.ps()
        
        status = {}
        for container in containers:
            service = container.labels.get("com.docker.compose.service", "unknown")
            status[service] = container.status
        
        return status

