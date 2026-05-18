"""
Test artifacts collector.

Собирает артефакты после выполнения тестов:
- Core dumps (coredump)
- Stack traces (backtrace)
- Application logs
- Monitoring metrics
- Container logs
- System info (при падении)
"""

import gzip
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel

from ..utils.logger import get_logger
from ..utils.cli import run_command, print_info, print_success, print_warning

logger = get_logger(__name__)


class ArtifactMetadata(BaseModel):
    """Metadata for collected artifact."""
    
    artifact_type: str  # coredump, log, trace, metric
    node_id: Optional[str] = None
    timestamp: str
    size_bytes: int
    compressed: bool = False
    source_path: str
    description: str


class ArtifactsCollector:
    """Collect test execution artifacts for debugging."""
    
    def __init__(self, base_path: Path):
        """
        Initialize artifacts collector.
        
        Args:
            base_path: Base path to stage-env directory
        """
        self.base_path = base_path
        self.artifacts_dir = base_path / "cache" / "crash-artifacts"
        self.logs_dir = base_path / "cache" / "logs"
        self.monitoring_dir = base_path / "cache" / "monitoring"
        
        # Create directories
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.monitoring_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("artifacts_collector_initialized",
                   artifacts_dir=str(self.artifacts_dir))
    
    def collect_on_crash(
        self,
        node_id: str,
        container_name: str,
        test_name: Optional[str] = None,
    ) -> Dict[str, any]:
        """
        Collect all artifacts when node crashes.
        
        Args:
            node_id: Node identifier
            container_name: Docker container name
            test_name: Test that was running
            
        Returns:
            Dict with collected artifacts info
        """
        timestamp = self._get_timestamp()
        session_dir = self.artifacts_dir / f"{node_id}_{timestamp}"
        session_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("collecting_crash_artifacts",
                   node_id=node_id,
                   test=test_name,
                   session=session_dir.name)
        
        print_info(f"Collecting crash artifacts for {node_id}...")
        
        collected = {
            "node_id": node_id,
            "container": container_name,
            "test_name": test_name,
            "timestamp": timestamp,
            "session_dir": str(session_dir),
            "artifacts": [],
        }
        
        # 1. Collect core dumps
        coredumps = self._collect_coredumps(container_name, session_dir, node_id)
        collected["artifacts"].extend(coredumps)
        
        # 2. Collect application logs
        app_logs = self._collect_app_logs(container_name, session_dir, node_id)
        collected["artifacts"].extend(app_logs)
        
        # 3. Collect backtrace (if available)
        backtrace = self._collect_backtrace(container_name, session_dir, node_id)
        if backtrace:
            collected["artifacts"].append(backtrace)
        
        # 4. Collect system info
        sysinfo = self._collect_system_info(container_name, session_dir, node_id)
        if sysinfo:
            collected["artifacts"].append(sysinfo)
        
        # 5. Collect monitoring data
        metrics = self._collect_monitoring_metrics(node_id, session_dir)
        collected["artifacts"].extend(metrics)
        
        # 6. Create summary
        self._create_summary(collected, session_dir)
        
        print_success(f"Collected {len(collected['artifacts'])} artifacts to {session_dir.name}")
        logger.info("crash_artifacts_collected",
                   count=len(collected['artifacts']),
                   session=session_dir.name)
        
        return collected
    
    def collect_all_logs(self, test_name: str) -> Path:
        """
        Collect logs from all containers for a test.
        
        Args:
            test_name: Name of the test
            
        Returns:
            Path to archive with logs
        """
        timestamp = self._get_timestamp()
        logs_session = self.logs_dir / f"{test_name}_{timestamp}"
        logs_session.mkdir(parents=True, exist_ok=True)
        
        logger.info("collecting_all_logs", test=test_name)
        
        # This will be called after test execution
        # Docker compose logs collection
        
        # Create tarball
        archive_path = self.logs_dir / f"{test_name}_{timestamp}.tar.gz"
        
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(logs_session, arcname=logs_session.name)
        
        # Remove temp dir
        shutil.rmtree(logs_session)
        
        logger.info("logs_archived", archive=str(archive_path))
        
        return archive_path
    
    def _collect_coredumps(
        self,
        container_name: str,
        output_dir: Path,
        node_id: str,
    ) -> List[ArtifactMetadata]:
        """Collect core dumps from container (running or stopped)."""
        
        logger.debug("collecting_coredumps", container=container_name)
        
        artifacts = []
        core_locations = [
            f"/crash-artifacts/node-{node_id}",
            "/tmp",
            "/var/crash",
        ]
        
        for location in core_locations:
            try:
                self._collect_cores_via_docker_cp(
                    container_name, location, output_dir, node_id, artifacts
                )
            except Exception as e:
                logger.debug("coredump_collection_skipped",
                            location=location, error=str(e))
        
        return artifacts
    
    def _collect_cores_via_docker_cp(
        self, container_name: str, location: str,
        output_dir: Path, node_id: str, artifacts: list,
    ):
        """Extract core dumps using docker cp (works on stopped containers)."""
        import io
        import docker
        
        try:
            client = docker.from_env(timeout=30)
            container = client.containers.get(container_name)
            stream, stat = container.get_archive(location + "/")
        except Exception:
            return
        
        tar_bytes = io.BytesIO()
        for chunk in stream:
            tar_bytes.write(chunk)
        tar_bytes.seek(0)
        
        try:
            with tarfile.open(fileobj=tar_bytes) as tar:
                for member in tar.getmembers():
                    basename = Path(member.name).name
                    if not member.isfile() or not (basename == "core" or basename.startswith("core.")):
                        continue
                    local_path = output_dir / f"coredump_{Path(member.name).name}"
                    with tar.extractfile(member) as src:
                        local_path.write_bytes(src.read())
                    
                    compressed_path = self._compress_file(local_path)
                    artifacts.append(ArtifactMetadata(
                        artifact_type="coredump",
                        node_id=node_id,
                        timestamp=self._get_timestamp(),
                        size_bytes=compressed_path.stat().st_size,
                        compressed=True,
                        source_path=f"{location}/{member.name}",
                        description=f"Core dump from {location}",
                    ))
                    logger.info("coredump_collected",
                               node_id=node_id,
                               source=f"{location}/{member.name}",
                               size_mb=compressed_path.stat().st_size / 1024 / 1024)
        except Exception as e:
            logger.debug("tar_extraction_failed", error=str(e))
    
    def _collect_app_logs(
        self,
        container_name: str,
        output_dir: Path,
        node_id: str,
    ) -> List[ArtifactMetadata]:
        """Collect application logs from container using docker cp (works on stopped containers)."""
        
        logger.debug("collecting_app_logs", container=container_name)
        
        artifacts = []
        
        log_paths = [
            "/opt/cellframe-node/var/log/cellframe-node.log",
        ]
        
        for log_path in log_paths:
            try:
                local_path = output_dir / f"log_{Path(log_path).name}"
                self._copy_from_container(container_name, log_path, local_path)
                
                if local_path.exists() and local_path.stat().st_size > 0:
                    compressed_path = self._compress_file(local_path)
                    artifacts.append(ArtifactMetadata(
                        artifact_type="log",
                        node_id=node_id,
                        timestamp=self._get_timestamp(),
                        size_bytes=compressed_path.stat().st_size,
                        compressed=True,
                        source_path=log_path,
                        description=f"Application log: {Path(log_path).name}",
                    ))
                    logger.info("app_log_collected", node_id=node_id,
                              source=log_path, size_mb=compressed_path.stat().st_size / 1024 / 1024)
            except Exception as e:
                logger.debug("log_collection_skipped", path=log_path, error=str(e))
        
        return artifacts
    
    def _collect_backtrace(
        self,
        container_name: str,
        output_dir: Path,
        node_id: str,
    ) -> Optional[ArtifactMetadata]:
        """Generate backtrace from core dump using GDB in a temporary helper container.
        
        Spins up a new container from the same image with the crash-artifacts
        volume mounted, runs GDB against the core dump, and captures the output.
        Works regardless of the original container's state.
        """
        
        logger.debug("collecting_backtrace", container=container_name)
        
        core_path = f"/crash-artifacts/node-{node_id}/core"
        binary_path = "/opt/cellframe-node/bin/cellframe-node"
        
        try:
            import docker as docker_lib
            client = docker_lib.from_env()
            
            src_container = client.containers.get(container_name)
            image = src_container.image.tags[0] if src_container.image.tags else src_container.image.id
            
            crash_volume = None
            for mount in src_container.attrs.get("Mounts", []):
                if mount.get("Destination", "").startswith("/crash-artifacts"):
                    crash_volume = mount["Source"]
                    break
            
            if not crash_volume:
                logger.warning("no_crash_artifacts_mount", container=container_name)
                return None
            
            gdb_cmd = (
                f"if [ ! -f {core_path} ]; then echo 'NO_CORE_DUMP'; exit 1; fi; "
                f"gdb -batch "
                f"-ex 'set pagination off' "
                f"-ex 'thread apply all bt full' "
                f"-ex 'info registers' "
                f"-ex 'info threads' "
                f"{binary_path} {core_path} 2>&1"
            )
            
            helper_name = f"gdb-helper-{node_id}"
            try:
                old = client.containers.get(helper_name)
                old.remove(force=True)
            except docker_lib.errors.NotFound:
                pass
            
            logger.info("running_gdb_helper", image=image, core=core_path)
            
            helper = client.containers.run(
                image,
                ["sh", "-c", gdb_cmd],
                name=helper_name,
                entrypoint="",
                volumes={crash_volume: {"bind": f"/crash-artifacts/node-{node_id}", "mode": "ro"}},
                remove=False,
                detach=True,
            )
            
            result = helper.wait(timeout=60)
            bt_text = helper.logs().decode("utf-8", errors="ignore")
            
            try:
                helper.remove(force=True)
            except Exception:
                pass
            
            if "NO_CORE_DUMP" in bt_text:
                logger.warning("no_core_dump_file", node_id=node_id, path=core_path)
                return None
            
            if not bt_text or len(bt_text.strip()) < 20:
                logger.warning("gdb_empty_backtrace", container=container_name,
                             exit_code=result.get("StatusCode"), output=bt_text[:500])
                return None
            
            bt_file = output_dir / "backtrace.txt"
            bt_file.write_text(bt_text)
            
            print(f"\n{'='*80}")
            print(f"STACK TRACE ({container_name}, node-{node_id}):")
            print(f"{'='*80}")
            for line in bt_text.split("\n")[:80]:
                print(line)
            if bt_text.count("\n") > 80:
                print(f"... ({bt_text.count(chr(10)) - 80} more lines in {bt_file})")
            print(f"{'='*80}\n")
            
            logger.info("backtrace_collected", node_id=node_id,
                       size=len(bt_text), file=str(bt_file))
            
            return ArtifactMetadata(
                artifact_type="backtrace",
                node_id=node_id,
                timestamp=self._get_timestamp(),
                size_bytes=bt_file.stat().st_size,
                compressed=False,
                source_path=core_path,
                description="GDB backtrace from core dump",
            )
        
        except Exception as e:
            logger.warning("backtrace_collection_failed", error=str(e))
            return None
    
    def _collect_system_info(
        self,
        container_name: str,
        output_dir: Path,
        node_id: str,
    ) -> Optional[ArtifactMetadata]:
        """Collect system information at crash time."""
        
        logger.debug("collecting_system_info", container=container_name)
        
        try:
            sysinfo = []
            
            # Collect various system info
            commands = [
                ("uname", ["uname", "-a"]),
                ("memory", ["free", "-h"]),
                ("disk", ["df", "-h"]),
                ("processes", ["ps", "aux"]),
                ("network", ["ip", "addr"]),
            ]
            
            for name, cmd in commands:
                try:
                    exit_code, output = self._exec_in_container(container_name, cmd)
                    if exit_code == 0:
                        sysinfo.append(f"=== {name.upper()} ===\n{output}\n")
                except Exception:
                    pass
            
            if sysinfo:
                sysinfo_file = output_dir / "system_info.txt"
                sysinfo_file.write_text("\n".join(sysinfo))
                
                return ArtifactMetadata(
                    artifact_type="sysinfo",
                    node_id=node_id,
                    timestamp=self._get_timestamp(),
                    size_bytes=sysinfo_file.stat().st_size,
                    compressed=False,
                    source_path="system",
                    description="System information at crash time",
                )
        
        except Exception as e:
            logger.debug("sysinfo_collection_failed", error=str(e))
        
        return None
    
    def _collect_monitoring_metrics(
        self,
        node_id: str,
        output_dir: Path,
    ) -> List[ArtifactMetadata]:
        """Collect monitoring metrics for the node."""
        
        logger.debug("collecting_monitoring_metrics", node_id=node_id)
        
        artifacts = []
        
        # Look for monitoring data in cache/monitoring/
        node_metrics = self.monitoring_dir / f"{node_id}_metrics.json"
        
        if node_metrics.exists():
            # Copy to artifacts
            shutil.copy(node_metrics, output_dir / "metrics.json")
            
            artifacts.append(ArtifactMetadata(
                artifact_type="metric",
                node_id=node_id,
                timestamp=self._get_timestamp(),
                size_bytes=node_metrics.stat().st_size,
                compressed=False,
                source_path=str(node_metrics),
                description="Monitoring metrics",
            ))
        
        return artifacts
    
    def _create_summary(self, collected: Dict, output_dir: Path) -> None:
        """Create summary report for collected artifacts."""
        
        import json
        
        summary_file = output_dir / "SUMMARY.json"
        
        with open(summary_file, "w") as f:
            json.dump(collected, f, indent=2, default=str)
        
        # Also create human-readable summary
        readme = output_dir / "README.txt"
        
        content = f"""
Crash Artifacts Collection
===========================

Node ID: {collected['node_id']}
Container: {collected['container']}
Test: {collected.get('test_name', 'N/A')}
Timestamp: {collected['timestamp']}

Collected Artifacts ({len(collected['artifacts'])} total):
"""
        
        for i, artifact in enumerate(collected['artifacts'], 1):
            if isinstance(artifact, ArtifactMetadata):
                content += f"\n{i}. {artifact.artifact_type.upper()}: {artifact.description}"
                content += f"\n   Size: {artifact.size_bytes / 1024:.1f} KB"
                content += f"\n   Source: {artifact.source_path}\n"
        
        readme.write_text(content)
    
    def _exec_in_container(
        self,
        container_name: str,
        command: List[str],
    ) -> tuple[int, str]:
        """Execute command in container."""
        
        cmd = ["docker", "exec", container_name] + command
        
        try:
            exit_code, stdout, stderr = run_command(cmd, check=False)
            return exit_code, stdout + stderr
        except Exception as e:
            logger.debug("exec_failed", error=str(e))
            return 1, ""
    
    def _copy_from_container(
        self,
        container_name: str,
        source_path: str,
        dest_path: Path,
    ) -> None:
        """Copy file from container to host."""
        
        cmd = ["docker", "cp", f"{container_name}:{source_path}", str(dest_path)]
        
        try:
            run_command(cmd, check=False)
        except Exception as e:
            logger.warning("copy_from_container_failed",
                         source=source_path,
                         error=str(e))
    
    def _compress_file(self, file_path: Path) -> Path:
        """Compress file with gzip."""
        
        compressed_path = file_path.with_suffix(file_path.suffix + ".gz")
        
        with open(file_path, "rb") as f_in:
            with gzip.open(compressed_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        
        # Remove original
        file_path.unlink()
        
        return compressed_path
    
    def _get_timestamp(self) -> str:
        """Get current timestamp string."""
        return datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    def list_artifacts(self) -> List[Dict[str, any]]:
        """
        List all collected artifact sessions.
        
        Returns:
            List of session info dicts
        """
        sessions = []
        
        for session_dir in sorted(self.artifacts_dir.iterdir(), reverse=True):
            if not session_dir.is_dir():
                continue
            
            summary_file = session_dir / "SUMMARY.json"
            
            if summary_file.exists():
                import json
                with open(summary_file) as f:
                    summary = json.load(f)
                    sessions.append({
                        "session": session_dir.name,
                        "node_id": summary.get("node_id"),
                        "timestamp": summary.get("timestamp"),
                        "artifacts_count": len(summary.get("artifacts", [])),
                        "path": str(session_dir),
                    })
        
        return sessions
    
    def clean_old_artifacts(self, keep_last: int = 10) -> None:
        """
        Clean old artifact sessions, keeping only recent ones.
        
        Args:
            keep_last: Number of recent sessions to keep
        """
        sessions = sorted(self.artifacts_dir.iterdir(), reverse=True)
        
        removed = 0
        for session_dir in sessions[keep_last:]:
            if session_dir.is_dir():
                shutil.rmtree(session_dir)
                removed += 1
        
        if removed > 0:
            print_info(f"Removed {removed} old artifact sessions")
            logger.info("old_artifacts_cleaned", removed=removed)

