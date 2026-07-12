"""
Node lifecycle management for Cellframe stagenet.

Handles graceful node shutdown, GDB flush verification, and restart operations.
"""

import asyncio
from typing import List, Optional

import docker

from src.utils.logger import get_logger
from src.utils.project import get_project_name


logger = get_logger(__name__)


class NodeLifecycleManager:
    """
    Manages node lifecycle operations with proper GDB persistence.
    
    Responsibilities:
    - Graceful node shutdown with GDB flush verification
    - Node restart with configuration reload
    - Health checks during lifecycle transitions
    """
    
    DOCKER_TIMEOUT = 30  # Default timeout for Docker API calls (seconds)
    
    def __init__(self, project_name: Optional[str] = None, docker_timeout: int = None):
        """
        Initialize node lifecycle manager.
        
        Args:
            project_name: Docker Compose project name
            docker_timeout: Timeout for Docker API calls in seconds
        """
        self.project_name = project_name if project_name is not None else get_project_name()
        self.docker_timeout = docker_timeout or self.DOCKER_TIMEOUT
        self.docker_client = docker.from_env(timeout=self.docker_timeout)
    
    async def graceful_shutdown_with_gdb_flush(
        self,
        service_names: List[str],
        flush_timeout: int = 60,
        check_interval: float = 2.0
    ) -> None:
        """
        Gracefully shutdown nodes and wait for GDB flush completion.
        
        Process:
        1. Send 'exit' command via CLI to each node
        2. Monitor container status until stopped
        3. Verify GDB files are flushed to disk
        
        Args:
            service_names: List of Docker Compose service names (e.g., ['node-1', 'node-2'])
            flush_timeout: Maximum time to wait for shutdown (seconds)
            check_interval: Check interval for container status (seconds)
            
        Raises:
            RuntimeError: If nodes don't stop within timeout
        """
        logger.info("graceful_shutdown_with_gdb_flush", 
                   services=service_names,
                   timeout=flush_timeout)
        
        # CRITICAL: Before shutdown, ensure all data is flushed to disk
        # Step 0: Sync filesystem to ensure buffered writes are persisted
        logger.info("syncing_filesystem_before_shutdown")
        
        for service in service_names:
            try:
                container_name = f"{self.project_name}-{service}"
                container = self.docker_client.containers.get(container_name)
                container.reload()
                
                if container.status != 'running':
                    logger.debug("container_already_stopped_skip_flush", container=container_name)
                    continue
                
                # Sync filesystem + GDB. docker SDK exec_run has no timeout= kwarg.
                logger.debug("syncing_filesystem_before_shutdown", container=container_name)
                cmd_sync = ["sh", "-c", "cellframe-node-cli global_db flush; sync"]
                container.exec_run(cmd_sync, demux=True)
                logger.debug("filesystem_synced_before_shutdown", container=container_name)
                
            except Exception as e:
                logger.warning("failed_to_sync_before_shutdown",
                             service=service,
                             error=str(e))
        
        # Step 1: Send 'exit' command to all nodes via CLI for graceful shutdown
        # Note: Both CLI 'exit' and SIGTERM call sig_exit_handler which does exit(0)
        # Chain files should be saved via fflush() in dap_chain_cell_file_append
        # Standard library should flush buffers on exit(0), but explicit sync helps
        logger.info("sending_exit_commands_to_nodes")
        for service in service_names:
            try:
                container_name = f"{self.project_name}-{service}"
                container = self.docker_client.containers.get(container_name)
                container.reload()
                
                if container.status != 'running':
                    logger.debug("container_already_stopped_skip", container=container_name)
                    continue
                
                # Send 'exit' command via cellframe-node-cli
                # docker SDK Container.exec_run() has no timeout= kwarg.
                logger.debug("sending_exit_command", container=container_name)
                cmd = ["sh", "-c", "cellframe-node-cli exit"]
                result = container.exec_run(cmd, demux=True)
                
                # Exit codes: 0=clean, 137=SIGKILL, 252=graceful shutdown - all are OK
                if result.exit_code in (0, 137, 252):
                    logger.debug("exit_command_sent", 
                                container=container_name,
                                exit_code=result.exit_code)
                else:
                    logger.warning("exit_command_unexpected_code",
                                  container=container_name,
                                  exit_code=result.exit_code)
                    
            except Exception as e:
                logger.warning("failed_to_send_exit_command",
                              service=service,
                              error=str(e))
        
        # Step 2: Monitor containers until they stop (GDB flush happens during shutdown)
        logger.info("monitoring_container_shutdown")
        
        import time
        start_time = time.time()
        
        while time.time() - start_time < flush_timeout:
            stopped_count = 0
            
            for service in service_names:
                try:
                    container_name = f"{self.project_name}-{service}"
                    container = self.docker_client.containers.get(container_name)
                    container.reload()  # Refresh status
                    
                    if container.status in ['exited', 'dead', 'removed']:
                        stopped_count += 1
                        logger.debug("container_stopped_gracefully",
                                    container=container_name,
                                    status=container.status)
                except docker.errors.NotFound:
                    # Container already removed
                    stopped_count += 1
                    logger.debug("container_not_found_assumed_stopped", service=service)
                except Exception as e:
                    logger.debug("container_status_check_error",
                                service=service,
                                error=str(e)[:100])
            
            # Check if all stopped
            if stopped_count >= len(service_names):
                elapsed = time.time() - start_time
                logger.info("all_nodes_stopped_gracefully",
                           services_count=len(service_names),
                           elapsed=f"{elapsed:.1f}s")
                
                # Additional wait for filesystem sync
                logger.info("waiting_for_filesystem_sync")
                await asyncio.sleep(3)
                
                return
            
            # Log progress
            elapsed = time.time() - start_time
            if int(elapsed) % 10 == 0 and elapsed > 1:
                logger.info("shutdown_progress",
                           stopped=stopped_count,
                           total=len(service_names),
                           elapsed=f"{elapsed:.1f}s")
            
            await asyncio.sleep(check_interval)
        
        # Timeout - force stop remaining containers
        logger.warning("graceful_shutdown_timeout_forcing_stop",
                      elapsed=flush_timeout)
        
        for service in service_names:
            try:
                container_name = f"{self.project_name}-{service}"
                container = self.docker_client.containers.get(container_name)
                container.reload()
                
                if container.status not in ['exited', 'dead']:
                    logger.warning("forcing_container_stop", container=container_name)
                    container.stop(timeout=10)  # Force stop
                    
            except Exception as e:
                logger.debug("force_stop_error", service=service, error=str(e)[:100])
        
        logger.info("shutdown_completed_with_force")
    
    async def verify_gdb_files_exist(
        self,
        node_ids: List[int],
        cache_path: str = None
    ) -> bool:
        """
        Verify GDB files exist on disk after shutdown.
        
        Args:
            node_ids: List of node IDs to check
            cache_path: Path to cache directory
            
        Returns:
            True if all nodes have GDB files
        """
        from pathlib import Path
        from ..config.manager import get_config_loader
        
        if cache_path is None:
            config_loader = get_config_loader()
            paths_config = config_loader.get_paths_config()
            base_path = Path(__file__).parent.parent.parent
            cache_path = str((base_path / paths_config.get('cache_dir', '../../cache')).resolve())
        
        logger.info("verifying_gdb_files_on_disk", nodes=len(node_ids))
        
        missing_count = 0
        
        for node_id in node_ids:
            # Correct path: .../nodeX/lib/global_db/gdb-mdbx/mdbx.dat
            gdb_file = Path(cache_path) / "data" / f"node{node_id}" / "lib" / "global_db" / "gdb-mdbx" / "mdbx.dat"
            
            if not gdb_file.exists():
                logger.warning("gdb_file_not_found",
                              node_id=node_id,
                              path=str(gdb_file))
                missing_count += 1
                continue
            
            # Check file size to ensure it's not just an empty placeholder
            file_size = gdb_file.stat().st_size
            if file_size < 1024:  # Less than 1KB is likely empty/corrupt
                logger.warning("gdb_file_too_small",
                              node_id=node_id,
                              size_bytes=file_size,
                              path=str(gdb_file))
                missing_count += 1
            else:
                logger.debug("gdb_file_verified",
                            node_id=node_id,
                            size_mb=round(file_size / 1024 / 1024, 2))
        
        if missing_count == 0:
            logger.info("all_gdb_files_verified", nodes=len(node_ids))
            return True
        else:
            logger.warning("some_gdb_files_missing",
                          missing=missing_count,
                          total=len(node_ids))
            return False
    
    async def hard_restart_with_config_reload(
        self,
        service_names: List[str],
        compose_manager,
        flush_timeout: int = 60,
        startup_timeout: int = 60
    ) -> None:
        """
        Hard restart: Full container restart WITH config reload (stops → starts).
        
        This is used to apply config changes that require full node restart:
        - static_genesis_block/event updates
        - Network topology changes
        Note: seed_mode in 6.x is controlled via CLI, no restart needed.
        
        Process:
        1. Graceful shutdown with GDB flush (preserves node list, GDB state)
        2. Verify GDB files on disk
        3. Restart containers (Docker compose up)
        4. Containers reload ALL configs from disk
        
        Args:
            service_names: List of Docker Compose service names
            compose_manager: DockerComposeManager instance for container control
            flush_timeout: Timeout for graceful shutdown (seconds)
            startup_timeout: Timeout for container startup (seconds)
        """
        logger.info("hard_restart_with_config_reload", 
                   services=service_names,
                   flush_timeout=flush_timeout)
        
        # Step 1: Graceful shutdown with GDB flush
        logger.info("gracefully_shutting_down_for_config_reload")
        await self.graceful_shutdown_with_gdb_flush(
            service_names=service_names,
            flush_timeout=flush_timeout
        )
        logger.info("shutdown_complete_gdb_flushed")
        
        # Step 2: Verify GDB persistence
        # Extract node IDs from service names (e.g., "node-1" → 1)
        node_ids = []
        for service in service_names:
            try:
                node_id = int(service.split('-')[-1])
                node_ids.append(node_id)
            except (ValueError, IndexError):
                logger.warning("could_not_extract_node_id", service=service)
        
        if node_ids:
            gdb_verified = await self.verify_gdb_files_exist(node_ids)
            if gdb_verified:
                logger.info("gdb_persistence_verified", nodes=len(node_ids))
            else:
                logger.warning("some_gdb_files_missing_continuing_anyway")
        
        # Step 3: Restart containers (configs will be reloaded)
        logger.info("restarting_containers_config_reload")
        logger.info("starting_services", services=service_names)
        compose_manager.up(services=service_names, detach=True, wait=False)
        logger.info("services_started")
        logger.info("containers_restarted_configs_reloaded")
    
    async def sequential_restart_with_config_reload(
        self,
        service_groups: List[List[str]],
        compose_manager,
        state_manager,
        flush_timeout: int = 60,
        startup_timeout: int = 60,
        inter_group_delay: float = 5.0
    ) -> None:
        """
        Sequential hard restart: Restart nodes group-by-group to maintain GDB sync.
        
        This prevents MDBX assertion crashes by ensuring at least some nodes
        are always online to provide GDB sync for node list.
        
        Critical for scenarios where:
        - All nodes need config reload (static_genesis_*)
        - Node list must be preserved via GDB
        - Simultaneous restart would cause empty node list
        
        Process:
        1. Restart first group → wait online
        2. Wait for GDB sync (ensures next group can get node list)
        3. Restart next group → previous groups provide GDB sync
        4. Repeat until all groups restarted
        
        Args:
            service_groups: List of service groups [[root nodes], [master nodes]]
                           e.g., [["node-1"], ["node-2"], ["node-3"], ["node-4", "node-5", "node-6"]]
            compose_manager: DockerComposeManager instance
            state_manager: NodeStateManager for waiting nodes online
            flush_timeout: Timeout for graceful shutdown (seconds)
            startup_timeout: Timeout for container startup (seconds)
            inter_group_delay: Delay between groups for GDB sync (seconds)
        """
        logger.info("sequential_restart_with_config_reload",
                   groups=len(service_groups),
                   total_services=sum(len(g) for g in service_groups))
        
        for group_idx, service_group in enumerate(service_groups, 1):
            logger.info("restarting_group",
                       group=group_idx,
                       total_groups=len(service_groups),
                       services=service_group)
            
            # Restart this group using standard hard restart
            await self.hard_restart_with_config_reload(
                service_names=service_group,
                compose_manager=compose_manager,
                flush_timeout=flush_timeout,
                startup_timeout=startup_timeout
            )
            
            # Extract node configs for state waiting
            from ..config.models import NodeConfig
            nodes_in_group = []
            for service in service_group:
                try:
                    node_id = int(service.split('-')[-1])
                    # Create minimal NodeConfig for state checking
                    node_config = NodeConfig(
                        node_id=node_id,
                        role="ROOT",  # Role doesn't matter for state checking
                        ip=f"172.20.0.{10 + node_id}",
                        port=8079
                    )
                    nodes_in_group.append(node_config)
                except (ValueError, IndexError) as e:
                    logger.warning("could_not_parse_service_name",
                                 service=service,
                                 error=str(e))
            
            # Wait for this group to come online
            if nodes_in_group and state_manager:
                logger.info("waiting_for_group_online",
                           group=group_idx,
                           nodes=len(nodes_in_group))
                try:
                    await state_manager.wait_for_nodes_online(
                        nodes_in_group,
                        timeout=startup_timeout
                    )
                    logger.info("group_online",
                               group=group_idx,
                               nodes=len(nodes_in_group))
                except TimeoutError as e:
                    logger.error("group_online_timeout",
                               group=group_idx,
                               error=str(e))
                    # Continue anyway - maybe nodes are initializing slowly
            
            # Wait for GDB sync before restarting next group
            # This ensures next group can get node list from already running nodes
            if group_idx < len(service_groups):
                logger.info("waiting_for_gdb_sync_before_next_group",
                           current_group=group_idx,
                           delay=inter_group_delay)
                await asyncio.sleep(inter_group_delay)
                logger.info("gdb_sync_delay_complete")
        
        logger.info("sequential_restart_complete",
                   groups=len(service_groups),
                   total_services=sum(len(g) for g in service_groups))

