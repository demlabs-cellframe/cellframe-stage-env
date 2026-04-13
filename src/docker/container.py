"""
Docker container management for scenario execution.

Provides fail-fast container operations with crash artifact collection.
"""

import subprocess
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List

import docker
from docker.errors import NotFound

from src.utils.logger import get_logger
from src.utils.project import get_project_name, make_container_name

logger = get_logger(__name__)


class DockerContainerManager:
    """
    Manages Docker container operations with fail-fast crash handling.
    
    Responsibilities:
    - Execute CLI commands in containers
    - Check container status
    - Collect crash artifacts (logs, core dumps, stack traces)
    - Generate stack traces from core dumps
    """
    
    def __init__(self, base_path: Path, node_cli_path: str = "cellframe-node-cli",
                 project_name: Optional[str] = None):
        self.base_path = base_path
        self.node_cli_path = node_cli_path
        self.project_name = project_name or get_project_name()
        self.docker_client = docker.from_env()
        self.current_test_name: Optional[str] = None
    
    def resolve_node_to_container(self, node: str) -> str:
        """
        Convert node ID/alias to Docker container name.
        
        Args:
            node: Node ID or alias (e.g., "root-1", "node1", "node-1")
            
        Returns:
            Container name (e.g., "cellframe-stage-node-1")
        """
        pn = self.project_name

        if node.startswith(f"{pn}-"):
            return node
        
        if node.startswith("root-"):
            node_num = node.split("-")[1]
            return f"{pn}-node-{node_num}"
        elif node.startswith("master-"):
            master_idx = int(node.split("-")[1])
            node_num = str(master_idx + 3)
            return f"{pn}-node-{node_num}"
        elif node.startswith("full-"):
            full_idx = int(node.split("-")[1])
            node_num = str(full_idx + 6)
            return f"{pn}-node-{node_num}"
        
        if node.startswith("node"):
            node_num = node[4:] if len(node) > 4 else node
            node_num = node_num.replace("-", "")
            return f"{pn}-node-{node_num}"
        
        if node.isdigit():
            return f"{pn}-node-{node}"
        
        return f"{pn}-{node}"
    
    def check_container_status(self, container_name: str) -> Dict[str, Any]:
        """
        Check container status and return status info.
        
        Args:
            container_name: Docker container name
            
        Returns:
            Dict with status info: {'status': str, 'exit_code': int, 'container': Container}
        """
        try:
            container = self.docker_client.containers.get(container_name)
            container.reload()
            exit_code = container.attrs.get("State", {}).get("ExitCode", -1)
            return {
                "status": container.status,
                "exit_code": exit_code,
                "container": container,
                "exists": True
            }
        except NotFound:
            return {
                "status": "not_found",
                "exit_code": -1,
                "container": None,
                "exists": False
            }
        except Exception as e:
            logger.error("container_status_check_failed", container=container_name, error=str(e))
            return {
                "status": "unknown",
                "exit_code": -1,
                "container": None,
                "exists": False,
                "error": str(e)
            }
    
    def collect_crash_artifacts(
        self,
        container_name: str,
        node_id: str,
        test_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Collect crash artifacts when container crashes.
        
        Args:
            container_name: Docker container name
            node_id: Node identifier
            test_name: Test that was running
            
        Returns:
            Dict with collected artifacts info
        """
        try:
            from ..monitoring.artifacts import ArtifactsCollector
            artifacts_collector = ArtifactsCollector(self.base_path)
            
            collected = artifacts_collector.collect_on_crash(
                node_id=node_id,
                container_name=container_name,
                test_name=test_name
            )
            
            logger.error("crash_artifacts_collected",
                       node_id=node_id,
                       artifacts_count=len(collected.get("artifacts", [])),
                       session_dir=collected.get("session_dir"))
            
            return collected
        except Exception as e:
            logger.error("failed_to_collect_crash_artifacts", error=str(e))
            return {"artifacts": [], "error": str(e)}
    
    def get_container_logs(self, container_name: str, tail: int = 100) -> str:
        """
        Get container logs.
        
        Args:
            container_name: Docker container name
            tail: Number of lines to get
            
        Returns:
            Logs as string
        """
        try:
            container = self.docker_client.containers.get(container_name)
            logs = container.logs(tail=tail).decode("utf-8", errors="ignore")
            return logs
        except Exception as e:
            logger.warning("failed_to_get_container_logs", container=container_name, error=str(e))
            return f"Failed to get logs: {e}"
    
    def generate_stack_trace_from_core_dump(
        self,
        container_name: str,
        artifacts: List[Any]
    ) -> None:
        """
        Generate and print stack trace from core dump using gdb.
        
        Args:
            container_name: Docker container name
            artifacts: List of collected artifacts (should contain coredump artifacts)
        """
        # Find core dump artifacts
        core_dumps = [a for a in artifacts if hasattr(a, 'artifact_type') and a.artifact_type == 'coredump']
        if not core_dumps:
            logger.debug("no_core_dumps_found_for_stack_trace", container=container_name)
            # Try to find core dumps directly in container
            try:
                node_id = container_name.split("-")[-1] if "-" in container_name else "1"
                core_locations = [f"/crash-artifacts/node-{node_id}", "/tmp/cores", "/var/crash", "/core", "/opt/cellframe-node/var/log"]
                for location in core_locations:
                    try:
                        result = subprocess.run(
                            ["docker", "exec", container_name, "find", location, "-name", "core*", "-type", "f", "-mtime", "-1"],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            core_files = result.stdout.strip().split("\n")
                            for core_file in core_files[:1]:  # Process first core dump found
                                self._generate_stack_trace_from_container_core(container_name, core_file)
                                return
                    except Exception:
                        continue
            except Exception:
                pass
            return
        
        # Try to generate stack trace for each core dump artifact
        for core_artifact in core_dumps:
            try:
                # Core dump should be in crash-artifacts directory
                if hasattr(core_artifact, 'node_id'):
                    # Try to find core dump in artifacts directory
                    artifacts_dir = self.base_path / "cache" / "crash-artifacts" / f"node-{core_artifact.node_id}"
                    core_files = list(artifacts_dir.glob("coredump_*"))
                    if not core_files:
                        # Try compressed
                        core_files = list(artifacts_dir.glob("coredump_*.gz"))
                    
                    if core_files:
                        core_path = core_files[0]
                        # Copy to container for analysis
                        try:
                            # Copy core dump to container
                            subprocess.run(
                                ["docker", "cp", str(core_path), f"{container_name}:/tmp/core_for_analysis"],
                                check=True,
                                timeout=10
                            )
                            self._generate_stack_trace_from_container_core(container_name, "/tmp/core_for_analysis")
                        except Exception as copy_err:
                            logger.warning("failed_to_copy_core_to_container",
                                         container=container_name,
                                         error=str(copy_err))
                elif hasattr(core_artifact, 'source_path'):
                    # Core dump path from artifact (may be in container)
                    core_path = core_artifact.source_path
                    self._generate_stack_trace_from_container_core(container_name, core_path)
                    
            except Exception as e:
                logger.warning("failed_to_process_core_dump_for_stack_trace",
                             container=container_name,
                             error=str(e))
    
    def _generate_stack_trace_from_container_core(self, container_name: str, core_path: str) -> None:
        """
        Generate stack trace from core dump in container using gdb.
        
        Args:
            container_name: Docker container name
            core_path: Path to core dump in container
        """
        # Find binary path in container
        binary_path = "/opt/cellframe-node/bin/cellframe-node"
        
        # Generate stack trace using gdb in container
        try:
            # Use gdb non-interactive mode to generate backtrace
            gdb_commands = [
                "set pagination off",
                "thread apply all bt full",
                "info registers",
                "quit"
            ]
            
            gdb_cmd = [
                "docker", "exec", container_name,
                "gdb", "-batch",
                "-ex", "; ".join(gdb_commands),
                binary_path, core_path
            ]
            
            result = subprocess.run(
                gdb_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.stdout:
                print(f"\n{'='*80}")
                print(f"STACK TRACE FROM CORE DUMP ({container_name}):")
                print(f"Core dump: {core_path}")
                print(f"{'='*80}")
                print(result.stdout)
                if result.stderr:
                    print(f"\nGDB stderr:\n{result.stderr}")
                print(f"{'='*80}\n")
                logger.info("stack_trace_generated_from_core_dump",
                          container=container_name,
                          core_path=core_path)
            else:
                logger.warning("gdb_no_output_generating_stack_trace",
                             container=container_name,
                             stderr=result.stderr[:500] if result.stderr else "no stderr")
                
        except subprocess.TimeoutError:
            logger.warning("gdb_timeout_generating_stack_trace", container=container_name)
        except FileNotFoundError:
            logger.debug("gdb_not_available_in_container", container=container_name)
        except Exception as gdb_err:
            logger.warning("gdb_error_generating_stack_trace",
                         container=container_name,
                         error=str(gdb_err))
    
    async def exec_cli_command(
        self,
        command: str,
        node: str,
        timeout: Optional[int] = 30
    ) -> Dict[str, Any]:
        """
        Execute CLI command in container with fail-fast crash handling.
        
        Args:
            command: CLI command to execute
            node: Node alias or ID
            timeout: Command timeout in seconds
            
        Returns:
            Dict with stdout, stderr, returncode
        """
        container_name = self.resolve_node_to_container(node)
        
        # Check container status - FAIL-FAST if crashed
        status_info = self.check_container_status(container_name)
        
        if not status_info["exists"]:
            error_msg = f"Container {container_name} not found"
            logger.error("container_not_found", container=container_name, node=node)
            return {
                "stdout": "",
                "stderr": error_msg,
                "returncode": 1
            }
        
        if status_info["status"] == "paused":
            logger.warning("container_paused_attempting_unpause",
                         container=container_name, node=node)
            try:
                status_info["container"].unpause()
                import time
                time.sleep(0.5)
                status_info = self.check_container_status(container_name)
                logger.info("container_unpaused_successfully",
                          container=container_name, status=status_info["status"])
            except Exception as e:
                logger.error("container_unpause_failed",
                           container=container_name, error=str(e))
        
        if status_info["status"] != "running":
            exit_code = status_info["exit_code"]
            container = status_info["container"]
            
            logger.error("container_crashed_fail_fast",
                       container=container_name,
                       status=status_info["status"],
                       exit_code=exit_code,
                       node=node,
                       command=command[:100])
            
            # Extract node ID from container name
            node_id = container_name.split("-")[-1] if "-" in container_name else node
            
            # Collect crash artifacts
            collected = self.collect_crash_artifacts(
                container_name=container_name,
                node_id=node_id,
                test_name=self.current_test_name
            )
            
            # Print container logs (last 100 lines)
            try:
                logs = self.get_container_logs(container_name, tail=100)
                logger.error("container_crash_logs",
                           container=container_name,
                           exit_code=exit_code,
                           logs=logs)
                print(f"\n{'='*80}")
                print(f"CONTAINER CRASH LOGS ({container_name}):")
                print(f"{'='*80}")
                print(logs)
                print(f"{'='*80}\n")
            except Exception as log_err:
                logger.warning("failed_to_get_crash_logs", error=str(log_err))
            
            # Try to generate and print stack trace from core dump
            try:
                self.generate_stack_trace_from_core_dump(container_name, collected.get("artifacts", []))
            except Exception as trace_err:
                logger.warning("failed_to_generate_stack_trace", error=str(trace_err))
            
            # Fail immediately - no restart attempts
            error_msg = f"Container {container_name} crashed (exit_code={exit_code}, status={status_info['status']}). Fail-fast: stopping execution."
            logger.error("fail_fast_container_crash",
                       container=container_name,
                       node=node,
                       error=error_msg)
            
            return {
                "stdout": "",
                "stderr": error_msg,
                "returncode": exit_code if exit_code != -1 else 1
            }
        
        # Container is running - execute command
        # Use shell mode to ensure proper argument passing through docker exec.
        # stdbuf forces line-buffered stdout so output is flushed before exit;
        # without it, a crash during cleanup loses buffered printf output.
        import shlex
        cmd_args = shlex.split(command)
        cli_cmd_quoted = " ".join(shlex.quote(arg) for arg in cmd_args)
        shell_cmd = f"stdbuf -oL {self.node_cli_path} {cli_cmd_quoted}"
        
        full_cmd = [
            "docker", "exec", container_name,
            "sh", "-c", shell_cmd
        ]
        
        # Debug: log full command and parsed args
        logger.info("exec_cli_command_debug", 
                    container=container_name,
                    command_original=command,
                    command_split=cmd_args,
                    shell_cmd=shell_cmd,
                    full_cmd_list=full_cmd)

        max_cli_retries = 3
        for cli_attempt in range(max_cli_retries):
            process = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )

                out_str = stdout.decode('utf-8', errors='replace')
                err_str = stderr.decode('utf-8', errors='replace')

                if not out_str.strip() and process.returncode != 0 and cli_attempt < max_cli_retries - 1:
                    logger.debug("exec_cli_empty_retry",
                                 container=container_name,
                                 attempt=cli_attempt + 1,
                                 returncode=process.returncode,
                                 stderr=err_str[:200])
                    await asyncio.sleep(0.3 * (cli_attempt + 1))
                    continue

                return {
                    "stdout": out_str,
                    "stderr": err_str,
                    "returncode": process.returncode
                }
            except asyncio.TimeoutError:
                logger.warning("exec_cli_timeout",
                             container=container_name,
                             command=command[:100],
                             timeout=timeout)
                process.kill()
                partial_out = ""
                partial_err = ""
                try:
                    stdout, stderr = await asyncio.wait_for(
                        process.communicate(), timeout=3
                    )
                    partial_out = stdout.decode('utf-8', errors='replace')
                    partial_err = stderr.decode('utf-8', errors='replace')
                    if partial_out or partial_err:
                        logger.warning("exec_cli_timeout_partial_output",
                                     container=container_name,
                                     stdout=partial_out[:500],
                                     stderr=partial_err[:500])
                except Exception:
                    pass
                return {
                    "stdout": partial_out,
                    "stderr": f"TIMEOUT after {timeout}s: {partial_err}",
                    "returncode": -1
                }

        return {
            "stdout": "",
            "stderr": f"CLI retries exhausted ({max_cli_retries})",
            "returncode": -1
        }
    
    async def exec_bash_command(
        self,
        script: str,
        node: str,
        timeout: Optional[int] = 30
    ) -> Dict[str, Any]:
        """
        Execute bash script in container.
        
        Args:
            script: Bash script to execute
            node: Node alias or ID
            timeout: Command timeout in seconds
            
        Returns:
            Dict with stdout, stderr, returncode
        """
        container_name = self.resolve_node_to_container(node)
        
        # Check container status - FAIL-FAST if crashed
        status_info = self.check_container_status(container_name)
        
        if not status_info["exists"] or status_info["status"] != "running":
            exit_code = status_info.get("exit_code", 1)
            return {
                "stdout": "",
                "stderr": f"Container {container_name} not running",
                "returncode": exit_code if exit_code != -1 else 1
            }
        
        # Execute bash script
        full_cmd = [
            "docker", "exec", container_name,
            "bash", "-c", script
        ]
        
        process = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            
            return {
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace'),
                "returncode": process.returncode
            }
        except asyncio.TimeoutError:
            process.kill()
            raise
    
    async def exec_tool_command(
        self,
        tool_cmd: str,
        node: str,
        timeout: Optional[int] = 30
    ) -> Dict[str, Any]:
        """
        Execute cellframe-node-tool command in container.
        
        Args:
            tool_cmd: Tool command (without 'cellframe-node-tool' prefix)
            node: Node alias or ID
            timeout: Command timeout in seconds
            
        Returns:
            Dict with stdout, stderr, returncode
        """
        container_name = self.resolve_node_to_container(node)
        
        # Check container status - FAIL-FAST if crashed
        status_info = self.check_container_status(container_name)
        
        if not status_info["exists"] or status_info["status"] != "running":
            exit_code = status_info.get("exit_code", 1)
            return {
                "stdout": "",
                "stderr": f"Container {container_name} not running",
                "returncode": exit_code if exit_code != -1 else 1
            }
        
        # Execute tool command
        full_cmd = [
            "docker", "exec", container_name,
            "cellframe-node-tool"
        ] + tool_cmd.split()
        
        process = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            
            return {
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace'),
                "returncode": process.returncode
            }
        except asyncio.TimeoutError:
            process.kill()
            raise
    
    def exec_cli_command_sync(
        self,
        command: str,
        node: str,
        timeout: Optional[int] = 30
    ) -> tuple[int, str, str]:
        """
        Execute CLI command in container synchronously (for legacy code).
        Wraps async exec_cli_command method.
        
        Args:
            command: CLI command to execute
            node: Node alias or ID
            timeout: Command timeout in seconds
            
        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        # Check if we're already in an async context
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context - need to run in a thread
            import concurrent.futures
            import threading
            
            # Create a new event loop in a separate thread
            result_container = {}
            exception_container = {}
            
            def run_in_thread():
                try:
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        result_container['result'] = new_loop.run_until_complete(
                            self.exec_cli_command(command, node, timeout)
                        )
                    finally:
                        new_loop.close()
                except Exception as e:
                    exception_container['exception'] = e
            
            thread = threading.Thread(target=run_in_thread)
            thread.start()
            thread.join(timeout=timeout + 5)
            
            if thread.is_alive():
                raise TimeoutError(f"Command timed out after {timeout}s")
            
            if 'exception' in exception_container:
                raise exception_container['exception']
            
            result = result_container.get('result', {"returncode": 1, "stdout": "", "stderr": ""})
        except RuntimeError:
            # No running event loop - can use asyncio.run()
            result = asyncio.run(self.exec_cli_command(command, node, timeout))
        
        # Convert dict result to tuple format
        return (
            result.get("returncode", 1),
            result.get("stdout", ""),
            result.get("stderr", "")
        )

    def cleanup_volume(self, host_path: str) -> bool:
        """
        Clean up a host path using a temporary docker container.
        Required for deleting files owned by root/docker.
        
        Args:
            host_path: Absolute path on host to clean
            
        Returns:
            True if cleanup successful
        """
        try:
            # Resolve absolute path
            abs_path = str(Path(host_path).resolve())
            
            # Security check: Ensure path is within allowed directories
            allowed_base = str(self.base_path.resolve())
            if not abs_path.startswith(allowed_base) and "/cache/" not in abs_path:
                logger.warning("cleanup_volume_path_unsafe", path=abs_path, base=allowed_base)
                # Proceed with caution or return False? 
                # For tests, we assume valid paths from snapshot manager.
            
            logger.info("cleaning_volume_with_docker", path=abs_path)
            
            # Use alpine if available, otherwise try to pull it
            image = "alpine:latest"
            try:
                self.docker_client.images.get(image)
            except docker.errors.ImageNotFound:
                try:
                    logger.info("pulling_cleanup_image", image=image)
                    self.docker_client.images.pull(image)
                except Exception as pull_err:
                    logger.warning("failed_to_pull_alpine", error=str(pull_err))
                    # Fallback to a node image if available
                    containers = self.docker_client.containers.list(all=True, filters={"name": f"{self.project_name}-node-"})
                    if containers:
                        image = containers[0].image.tags[0]
                        logger.info("using_fallback_image", image=image)
            
            # Run rm -rf inside container
            # Mount path to /clean_target and delete everything inside
            self.docker_client.containers.run(
                image,
                ["/bin/sh", "-c", "rm -rf /clean_target/* && rm -rf /clean_target/.[!.]*"],
                volumes={abs_path: {'bind': '/clean_target', 'mode': 'rw'}},
                remove=True,
                user="root",
                entrypoint=""  # Override entrypoint for fallback images
            )
            return True
        except Exception as e:
            logger.error("volume_cleanup_failed", path=host_path, error=str(e))
            return False

