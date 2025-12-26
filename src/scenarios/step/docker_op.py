"""
Docker operation step executor.
"""

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import DockerOpStep, WaitStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class DockerOpStepExecutor(StepExecutor):
    """Executor for Docker operation steps."""
    
    def __init__(
        self,
        container_manager,
        log_file=None,
        debug: bool = False,
        resolve_node_alias_callback=None,
        wait_executor=None
    ):
        """Initialize Docker op executor."""
        super().__init__(container_manager, log_file, debug)
        self.resolve_node_alias_callback = resolve_node_alias_callback
        self.wait_executor = wait_executor
    
    async def execute(self, step: DockerOpStep, ctx: RuntimeContext) -> None:
        """Execute Docker operation step."""
        operation = ctx.substitute(step.docker_op)
        
        # Handle cp operation separately - doesn't need services
        if operation == "cp":
            logger.info(f"Docker operation: cp (src={step.src}, dst={step.dst})")
            await self._execute_cp(step, ctx)
            return
        
        logger.info(f"Docker operation: {operation} on services {step.services}")
        
        # Handle services - can be a list or a template string that expands to a list
        raw_services = step.services
        if raw_services is None:
            raise ScenarioExecutionError(f"services required for '{operation}' operation", step=step)
        if isinstance(raw_services, str):
            # Template string like "{{all_nodes}}" - substitute and parse
            expanded = ctx.substitute(raw_services)
            # After substitution, should be a list representation or comma-separated
            if expanded.startswith('[') and expanded.endswith(']'):
                # Parse as Python list literal
                import ast
                try:
                    raw_services = ast.literal_eval(expanded)
                except (ValueError, SyntaxError):
                    # Fallback: treat as single service
                    raw_services = [expanded]
            else:
                # Comma-separated or single value
                raw_services = [s.strip() for s in expanded.split(',') if s.strip()]
        
        # Handle services - can be a list or a template string that expands to a list
        raw_services = step.services
        if isinstance(raw_services, str):
            # Template string like "{{all_nodes}}" - substitute and parse
            expanded = ctx.substitute(raw_services)
            # After substitution, should be a list representation or comma-separated
            if expanded.startswith('[') and expanded.endswith(']'):
                # Parse as Python list literal
                import ast
                try:
                    raw_services = ast.literal_eval(expanded)
                except (ValueError, SyntaxError):
                    # Fallback: treat as single service
                    raw_services = [expanded]
            else:
                # Comma-separated or single value
                raw_services = [s.strip() for s in expanded.split(',') if s.strip()]
        
        # Substitute variables and resolve node aliases to docker service names
        # Docker services use format: node-1, node-2, etc.
        # But scenarios may use: root-1, master-1, node-1, etc.
        services = []
        for s in raw_services:
            substituted = ctx.substitute(s)
            
            # Direct docker service name (node-1, node-2, etc.)
            if substituted.startswith("node-") and len(substituted) > 5:
                docker_service = substituted
            # Resolve node alias (root-1 -> node1) then convert to docker service name (node1 -> node-1)
            else:
                if not self.resolve_node_alias_callback:
                    raise RuntimeError("resolve_node_alias_callback not set for DockerOpStepExecutor")
                resolved = self.resolve_node_alias_callback(substituted)
                # Convert node1 -> node-1 for docker-compose service names
                if resolved.startswith("node") and len(resolved) > 4:
                    node_num = resolved[4:]  # Extract number from node1, node2, etc.
                    docker_service = f"node-{node_num}"
                # Handle role-based aliases directly for default topology
                # root-1, root-2, root-3 -> node-1, node-2, node-3
                elif substituted.startswith("root-"):
                    node_num = substituted.split("-")[1]
                    docker_service = f"node-{node_num}"
                # master-1, master-2, master-3 -> node-4, node-5, node-6 (in default topology)
                elif substituted.startswith("master-"):
                    master_idx = int(substituted.split("-")[1])
                    node_num = str(master_idx + 3)  # master-1 -> node-4, master-2 -> node-5, etc.
                    docker_service = f"node-{node_num}"
                else:
                    # Fallback: use as-is
                    docker_service = resolved
            services.append(docker_service)
        
        # Get DockerComposeManager - need to get it from context
        if not hasattr(ctx, 'compose_manager'):
            raise ScenarioExecutionError(
                "DockerComposeManager not available in context. "
                "Docker operations require NetworkManager to be set in RuntimeContext.",
                step=step
            )
        
        compose_manager = ctx.compose_manager
        
        try:
            if operation == "start":
                compose_manager.up(services=services, detach=step.detach, wait=False)
                
                # Wait for containers to receive IP addresses
                if step.wait_for_ip:
                    from ...monitoring.waiter.docker_ip_waiter import DockerIPWaiter
                    
                    ip_waiter = DockerIPWaiter(self.container_manager.docker_client)
                    
                    # Map docker service names to container names
                    # node-1 -> cellframe-stage-node-1
                    container_names = [f"cellframe-stage-{svc}" for svc in services]
                    
                    logger.info("waiting_for_container_ips", containers=container_names)
                    
                    if not ip_waiter.wait_for_container_ips(container_names, timeout=30.0):
                        raise ScenarioExecutionError(
                            f"Containers did not receive IP addresses within timeout: {container_names}"
                        )
                    
                    logger.info("✅ All containers have IP addresses", count=len(container_names))
            
            elif operation == "recreate":
                # Force recreate containers to pick up new volume data (e.g., after snapshot restore)
                compose_manager.up(services=services, detach=step.detach, wait=False, force_recreate=True)
                
                # Wait for containers to receive IP addresses
                if step.wait_for_ip:
                    from ...monitoring.waiter.docker_ip_waiter import DockerIPWaiter
                    
                    ip_waiter = DockerIPWaiter(self.container_manager.docker_client)
                    container_names = [f"cellframe-stage-{svc}" for svc in services]
                    
                    logger.info("waiting_for_container_ips", containers=container_names)
                    
                    if not ip_waiter.wait_for_container_ips(container_names, timeout=30.0):
                        raise ScenarioExecutionError(
                            f"Containers did not receive IP addresses within timeout: {container_names}"
                        )
                    
                    logger.info("✅ All containers have IP addresses", count=len(container_names))
                
            elif operation == "stop":
                # Stop all containers gracefully (docker compose stop)
                # Note: kill() stops all containers, not just specific services
                compose_manager.kill(timeout=10)
            elif operation == "restart":
                compose_manager.restart(services=services)
            elif operation == "logs":
                # Logs operation - would need to implement
                logger.warning("Docker logs operation not yet implemented")
            elif operation == "exec":
                if not step.command:
                    raise ScenarioExecutionError("Command required for 'exec' operation", step=step)
                # Exec operation - would need to implement
                logger.warning("Docker exec operation not yet implemented")
            else:
                raise ScenarioExecutionError(f"Unknown Docker operation: {operation}", step=step)
            
            # Wait if specified
            if step.wait:
                if not self.wait_executor:
                    raise RuntimeError("wait_executor not set for DockerOpStepExecutor")
                await self.wait_executor.execute(WaitStep(wait=step.wait), ctx)
            
            logger.info(f"✅ Docker operation '{operation}' completed")
            ctx.add_result("docker_op", True, {"operation": operation, "services": services})
            
        except Exception as e:
            error_msg = f"Docker operation failed: {str(e)}"
            logger.error(error_msg)
            ctx.add_result("docker_op", False, {"operation": operation, "error": str(e)})
            raise ScenarioExecutionError(error_msg, step=step)
    
    async def _execute_cp(self, step: DockerOpStep, ctx: RuntimeContext) -> None:
        """
        Execute docker cp operation.
        
        Supports copying between containers or between host and container.
        Format: "node-1:/path/in/container" or "/host/path"
        """
        import subprocess
        import tempfile
        import os
        
        if not step.src or not step.dst:
            raise ScenarioExecutionError("src and dst required for 'cp' operation", step=step)
        
        src = ctx.substitute(step.src)
        dst = ctx.substitute(step.dst)
        
        def parse_path(path: str) -> tuple:
            """Parse path into (container_name, path). Container is None for host paths."""
            if ':' in path and not path.startswith('/'):
                parts = path.split(':', 1)
                container = parts[0]
                # Convert node-1 to cellframe-stage-node-1
                if container.startswith('node-'):
                    container = f"cellframe-stage-{container}"
                return container, parts[1]
            return None, path
        
        src_container, src_path = parse_path(src)
        dst_container, dst_path = parse_path(dst)
        
        logger.info(f"Docker cp: {src} -> {dst}")
        
        try:
            if src_container and dst_container:
                # Container to container: use temp file on host
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    tmp_path = tmp.name
                try:
                    # Copy from source container to host temp
                    subprocess.run(
                        ["docker", "cp", f"{src_container}:{src_path}", tmp_path],
                        check=True, capture_output=True, text=True
                    )
                    # Copy from host temp to destination container
                    subprocess.run(
                        ["docker", "cp", tmp_path, f"{dst_container}:{dst_path}"],
                        check=True, capture_output=True, text=True
                    )
                finally:
                    os.unlink(tmp_path)
            elif src_container:
                # Container to host
                subprocess.run(
                    ["docker", "cp", f"{src_container}:{src_path}", dst_path],
                    check=True, capture_output=True, text=True
                )
            elif dst_container:
                # Host to container
                subprocess.run(
                    ["docker", "cp", src_path, f"{dst_container}:{dst_path}"],
                    check=True, capture_output=True, text=True
                )
            else:
                # Host to host - just use shutil
                import shutil
                shutil.copy2(src_path, dst_path)
            
            logger.info(f"✓ Copied {src} to {dst}")
            
        except subprocess.CalledProcessError as e:
            raise ScenarioExecutionError(
                f"Docker cp failed: {e.stderr or e.stdout or str(e)}", step=step
            )

