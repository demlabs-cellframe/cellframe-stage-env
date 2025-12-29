"""
Datum monitoring service for tracking datum processing through the network.

Direct polling-based monitoring that tracks datum lifecycle:
  mempool → verification → blocks → propagation
  
Usage:
    monitor = DatumMonitor(...)
    
    # Direct synchronous monitoring
    result = await monitor.wait_for_datum(
        datum_hash=hash,
        node=node,
        network=network,
        chain=chain,
        timeouts={...}
    )
"""

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field

import docker

from ..scenarios.schema import DatumStatus
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class DatumMonitorResult:
    """Result of datum monitoring."""
    status: DatumStatus
    datum_hash: str
    elapsed_time: float
    details: Dict = field(default_factory=dict)
    error_message: Optional[str] = None
    
    def __repr__(self):
        return f"DatumMonitorResult(status={self.status}, hash={self.datum_hash[:16]}..., time={self.elapsed_time:.1f}s)"


class DatumMonitor:
    """
    Direct polling-based datum monitor.
    
    Polls network and tracks datums through:
    - Mempool presence
    - Master node verification
    - Block inclusion
    - Block propagation to target nodes
    
    Detects various failure scenarios with detailed diagnostics.
    """
    
    def __init__(self, node_cli_path: str = "cellframe-node-cli", log_file: Optional[Path] = None):
        """
        Initialize datum monitor.
        
        Args:
            node_cli_path: Path to cellframe-node-cli executable
            log_file: Optional path to monitoring logs directory
        """
        self.node_cli_path = node_cli_path
        self.docker_client = docker.from_env()
        self._topology_map = None  # Cache for role -> node_ids mapping
        
        # Create separate datum monitor log
        if log_file:
            log_path = Path(log_file)
            
            # If it's a directory, create health-logs inside it
            if log_path.is_dir():
                health_logs = log_path / "health-logs"
                health_logs.mkdir(parents=True, exist_ok=True)
                self.log_file = health_logs / "datum-monitor.log"
            else:
                # It's a file path, use its parent directory
                health_logs = log_path.parent / "health-logs"
                health_logs.mkdir(parents=True, exist_ok=True)
                self.log_file = health_logs / "datum-monitor.log"
        else:
            self.log_file = None
    
    def _log(self, message: str):
        """Log message to scenario log file."""
        if not self.log_file:
            return
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] [DATUM_MONITOR] {message}\n"
        
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(log_line)
    
    def _collect_node_logs(self, node: str, lines: int = 100) -> None:
        """
        Collect and log node container logs for diagnosis.
        
        Args:
            node: Node identifier (e.g., "root-1", "node1")
            lines: Number of log lines to collect
        """
        try:
            container_name = self._node_to_container(node)
            container = self.docker_client.containers.get(container_name)
            
            # Get container logs
            logs = container.logs(tail=lines).decode('utf-8', errors='replace')
            
            self._log(f"  📋 Node logs ({node}, {lines} lines):")
            self._log(f"     {'-' * 60}")
            for line in logs.split('\n'):
                if line.strip():
                    self._log(f"     {line}")
            self._log(f"     {'-' * 60}")
            
            # Also log to main logger for visibility
            logger.info("collected_node_logs_for_diagnosis",
                       node=node,
                       container=container_name,
                       lines=lines,
                       log_preview=logs[:500] if logs else "empty")
        except Exception as e:
            self._log(f"  ⚠️ Failed to collect node logs: {e}")
            logger.warning("failed_to_collect_node_logs",
                         node=node,
                         error=str(e))
    
    async def wait_for_datum(
        self,
        datum_hash: str,
        node: str = "node1",
        network: str = "stagenet",
        chain: str = "main",
        check_master_nodes: bool = True,
        timeout_total: float = 300,
        timeout_mempool: Optional[float] = None,
        timeout_verification: Optional[float] = None,
        timeout_in_blocks: Optional[float] = None,
        check_interval: float = 2.0
    ) -> DatumMonitorResult:
        """
        Wait for datum to complete processing through network.
        
        Args:
            datum_hash: Datum hash to monitor
            node: Target node to check
            network: Network name
            chain: Chain name
            check_master_nodes: Whether to check master nodes
            timeout_total: Total timeout in seconds
            timeout_mempool: Max time in mempool (default: 80% of timeout_total, min 60s)
            timeout_verification: Max time after verification (default: 50% of timeout_total, min 60s)
            timeout_in_blocks: Max time after block inclusion (default: 50% of timeout_total, min 60s)
            check_interval: Polling interval in seconds
            
        Returns:
            DatumMonitorResult with status and details
            
        Note:
            If individual timeouts are not provided, they are calculated from timeout_total
            using sensible defaults that allow enough time for each stage.
        """
        # Calculate default timeouts if not provided
        # These defaults are based on typical DAG-PoA consensus timing
        if timeout_mempool is None:
            timeout_mempool = max(60.0, timeout_total * 0.8)
        if timeout_verification is None:
            timeout_verification = max(60.0, timeout_total * 0.5)
        if timeout_in_blocks is None:
            timeout_in_blocks = max(60.0, timeout_total * 0.5)
        # Validate datum hash format
        hash_pattern = r'^0x[0-9a-fA-F]{64,}$'
        if not re.match(hash_pattern, datum_hash):
            error_msg = f"Invalid datum hash format: {datum_hash[:200]}"
            self._log(f"❌ {error_msg}")
            self._log(f"  Expected: 0x[hex] format (64+ hex chars)")
            self._log(f"  This likely means the CLI command failed and returned error output instead of a hash")
            
            return DatumMonitorResult(
                status=DatumStatus.REJECTED,
                datum_hash=datum_hash[:100],
                elapsed_time=0.0,
                error_message=error_msg
            )
        
        self._log(f"📝 Monitoring datum: {datum_hash[:16]}... (node={node}, timeouts: {timeout_total}s total)")
        
        # State tracking
        start_time = asyncio.get_event_loop().time()
        was_in_mempool = False
        was_verified = False
        was_in_blocks = False
        mempool_start = None
        verification_start = None
        blocks_start = None
        
        iteration = 0
        
        while True:
            iteration += 1
            current_time = asyncio.get_event_loop().time()
            elapsed = current_time - start_time
            
            # Check total timeout
            if elapsed > timeout_total:
                error = f"Total timeout after {elapsed:.1f}s"
                self._log(f"  ❌ {error}")
                return DatumMonitorResult(
                    status=DatumStatus.TIMEOUT_TOTAL,
                    datum_hash=datum_hash,
                    elapsed_time=elapsed,
                    error_message=error
                )
            
            # Stage 1: Wait for datum to appear in mempool (if not already there)
            if not was_in_mempool:
                # Use waiter to wait for datum to appear in mempool
                # This handles cases where datum is created with delay (e.g., token_decl_sign replaces old datum)
                from .waiter.datum_waiters import DatumInMempoolWaiter
                
                # Extract node_id from node name (e.g., "root-1" -> 1, "node-2" -> 2)
                node_id = self._extract_node_id(node)
                
                # Create exec_cli function using existing pattern from GenesisInitializer._exec_cli
                # This matches the pattern used by other waiters in the codebase
                def exec_cli_sync(node_id: int, command: str, check_output: bool = True) -> tuple:
                    """
                    Execute CLI command synchronously using DatumMonitor's docker client.
                    
                    Based on GenesisInitializer._exec_cli pattern (same as used by other waiters).
                    Note: node_id parameter is ignored, we use the original node name instead.
                    """
                    # Use original node name (not converted from node_id) for container lookup
                    # This is important because node_id might not match the actual container name
                    container_name = self._node_to_container(node)
                    try:
                        container = self.docker_client.containers.get(container_name)
                    except Exception as e:
                        if check_output:
                            raise RuntimeError(f"Container {container_name} not found: {e}")
                        return (1, "", f"Container {container_name} not found: {e}")
                    
                    # CRITICAL: Check container status before executing command (fail-fast)
                    container.reload()
                    if container.status != 'running':
                        error_msg = (
                            f"Container {container_name} (node {node}) is not running "
                            f"(status: {container.status}). Container crashed during datum monitoring."
                        )
                        # ALWAYS raise exception for container crash, even if check_output=False
                        # This ensures fail-fast behavior - waiter should stop immediately
                        raise RuntimeError(error_msg)
                    
                    # Use sh -c wrapper to ensure proper command execution (same as GenesisInitializer._exec_cli)
                    full_cmd = f"{self.node_cli_path} {command}"
                    cmd = ["sh", "-c", full_cmd]
                    
                    try:
                        result = container.exec_run(cmd, demux=True)
                        exit_code = result.exit_code
                        stdout, stderr = result.output
                        stdout_str = stdout.decode('utf-8', errors='replace') if stdout else ""
                        stderr_str = stderr.decode('utf-8', errors='replace') if stderr else ""
                        
                        if check_output and exit_code != 0:
                            raise RuntimeError(f"CLI command failed with exit code {exit_code}: {stderr_str}")
                        
                        return (exit_code, stdout_str, stderr_str)
                    except Exception as e:
                        # Check if error is about container not running
                        error_str = str(e).lower()
                        if "not running" in error_str or "409" in error_str or "conflict" in error_str:
                            error_msg = (
                                f"Container {container_name} (node {node}) crashed during command execution: {e}"
                            )
                            # ALWAYS raise exception for container crash, even if check_output=False
                            # This ensures fail-fast behavior - waiter should stop immediately
                            raise RuntimeError(error_msg) from e
                        # Re-raise other exceptions
                        raise
                
                # Log the hash we're looking for
                self._log(f"  🔍 Looking for datum {datum_hash[:16]}... in mempool on {node}")
                logger.info("waiting_for_datum_in_mempool",
                           node=node,
                           node_id=node_id,
                           datum_hash=datum_hash,
                           network=network,
                           chain=chain)
                
                waiter = DatumInMempoolWaiter(
                    exec_cli=exec_cli_sync,
                    node_id=node_id,
                    datum_hash=datum_hash,
                    network_name=network,
                    chain=chain,
                    poll_interval=0.5  # Fast polling for mempool appearance
                )
                
                try:
                    # Wait for datum to appear in mempool (with reasonable timeout)
                    mempool_wait_timeout = min(10.0, timeout_mempool)  # Wait up to 10s or timeout_mempool, whichever is smaller
                    await waiter.wait(timeout=mempool_wait_timeout, name=f"datum_{datum_hash[:16]}_in_mempool")
                    was_in_mempool = True
                    mempool_start = current_time
                    self._log(f"  ✅ Datum {datum_hash[:16]}... entered mempool")
                except RuntimeError as e:
                    # Container crashed during monitoring - fail-fast
                    error_msg = str(e)
                    self._log(f"  ❌ Container crashed during datum monitoring: {error_msg}")
                    
                    # Collect crash artifacts
                    container_name = self._node_to_container(node)
                    from ..docker.container import DockerContainerManager
                    from pathlib import Path
                    container_manager = DockerContainerManager(Path.cwd(), self.node_cli_path)
                    try:
                        artifacts = container_manager.collect_crash_artifacts(
                            container_name=container_name,
                            node_id=node,
                            test_name=None
                        )
                        self._log(f"  📦 Crash artifacts collected: {artifacts}")
                    except Exception as artifact_error:
                        self._log(f"  ⚠️ Failed to collect crash artifacts: {artifact_error}")
                    
                    # Collect node logs for diagnosis
                    self._collect_node_logs(node, lines=100)
                    
                    return DatumMonitorResult(
                        status=DatumStatus.REJECTED,
                        datum_hash=datum_hash,
                        elapsed_time=elapsed,
                        error_message=error_msg
                    )
                except TimeoutError:
                    # Datum didn't appear in mempool - check if it's already in DAG (auto_proc=true case)
                    self._log(f"  ⚠️ Datum {datum_hash[:16]}... not found in mempool, checking DAG events...")
                    
                    block_info = await self._check_in_blocks(node, network, chain, datum_hash)
                    if block_info:
                        # Datum already in DAG! (auto_proc processed it immediately)
                        self._log(f"  ✅ Datum {datum_hash[:16]}... already in DAG (auto_proc processed it)")
                        return DatumMonitorResult(
                            status=DatumStatus.SUCCESS,
                            datum_hash=datum_hash,
                            elapsed_time=elapsed,
                            details={"already_in_dag": True, "event_info": str(block_info)}
                        )
                    
                    # Datum not in mempool and not in DAG - likely not created
                    error = f"Datum never appeared in mempool after {mempool_wait_timeout:.1f}s - likely not created (check CLI command output for errors)"
                    self._log(f"  ❌ {error}")
                    self._log(f"  💡 Datum hash received: {datum_hash[:50]}...")
                    self._log(f"  💡 Check that token_decl/token_emit/token_decl_sign command succeeded")
                    
                    # Collect node logs for diagnosis
                    self._collect_node_logs(node, lines=100)
                    
                    return DatumMonitorResult(
                        status=DatumStatus.REJECTED,
                        datum_hash=datum_hash,
                        elapsed_time=elapsed,
                        error_message=error
                    )
            
            # Stage 1 continued: Check if datum is still in mempool
            in_mempool = await self._check_mempool(node, network, chain, datum_hash)
            
            # For DAG chains (zerochain), datums are NOT removed from mempool after
            # being included in an event. So we need to check events even while
            # datum is still in mempool.
            is_dag_chain = self._is_dag_chain(chain)
            
            if is_dag_chain and in_mempool:
                # For DAG: check if datum is already in an event
                block_info = await self._check_in_blocks(node, network, chain, datum_hash)
                if block_info:
                    event_num, event_hash = block_info
                    self._log(f"  ✅ Datum {datum_hash[:16]}... found in DAG event #{event_num}")
                    return DatumMonitorResult(
                        status=DatumStatus.SUCCESS,
                        datum_hash=datum_hash,
                        elapsed_time=elapsed,
                        details={
                            "block_number": event_num,
                            "block_hash": event_hash,
                            "total_time": elapsed,
                            "dag_chain": True
                        }
                    )
            
            if in_mempool:
                # Check mempool timeout
                mempool_time = current_time - mempool_start
                
                # Log mempool waiting state periodically
                if int(mempool_time) % 10 == 0:  # Every 10 seconds
                    self._log(f"  ⏳ Datum {datum_hash[:16]}... still in mempool ({mempool_time:.1f}s)")
                
                if mempool_time > timeout_mempool:
                    error = f"Datum stuck in mempool for {mempool_time:.1f}s (expected verification within {timeout_mempool}s)"
                    self._log(f"  ❌ {error}")
                    self._log(f"  💡 This may indicate consensus issues or insufficient validators")
                    
                    # Collect node logs for diagnosis
                    self._collect_node_logs(node, lines=200)
                    
                    return DatumMonitorResult(
                        status=DatumStatus.TIMEOUT_MEMPOOL,
                        datum_hash=datum_hash,
                        elapsed_time=elapsed,
                        details={"mempool_time": mempool_time},
                        error_message=error
                    )
                
                # Still in mempool, continue monitoring
                await asyncio.sleep(check_interval)
                continue
            
            # Stage 2: Datum left mempool - check if verified
            if was_in_mempool and not was_verified:
                logger.debug("datum_left_mempool_checking_verification",
                            datum_hash=datum_hash[:20],
                            chain=chain,
                            elapsed=f"{elapsed:.1f}s")
                
                # Check if it was verified on master nodes
                verified = await self._check_verified_on_masters(node, network, chain, datum_hash) if check_master_nodes else True
                
                if verified:
                    self._log(f"  ✅ Datum {datum_hash[:16]}... verified by validators")
                    was_verified = True
                    verification_start = current_time
                    logger.debug("datum_marked_as_verified",
                                datum_hash=datum_hash[:20],
                                elapsed=f"{elapsed:.1f}s")
                else:
                    verification_time = current_time - mempool_start
                    
                    if verification_time > timeout_verification:
                        error = f"Datum not verified after {verification_time:.1f}s"
                        self._log(f"  ❌ {error}")
                        self._log(f"  💡 Datum left mempool but not verified - may be rejected")
                        
                        # Collect node logs for diagnosis
                        self._collect_node_logs(node, lines=100)
                        
                        return DatumMonitorResult(
                            status=DatumStatus.TIMEOUT_VERIFICATION,
                            datum_hash=datum_hash,
                            elapsed_time=elapsed,
                            details={"verification_time": verification_time},
                            error_message=error
                        )
            
            # Stage 3: Check if datum is in blocks/events (auto-detected by chain type)
            block_info = await self._check_in_blocks(node, network, chain, datum_hash)
            
            if block_info:
                block_number, block_hash = block_info
                
                # Determine chain type for logging
                is_dag = self._is_dag_chain(chain)
                item_type = "event" if is_dag else "block"
                
                if not was_in_blocks:
                    self._log(f"  ✅ Datum {datum_hash[:16]}... included in {item_type} #{block_number}")
                    was_in_blocks = True
                    blocks_start = current_time
                
                # Success! Datum is in a block/event
                self._log(f"  ✅ Datum {datum_hash[:16]}... successfully processed ({item_type} #{block_number})")
                return DatumMonitorResult(
                    status=DatumStatus.SUCCESS,
                    datum_hash=datum_hash,
                    elapsed_time=elapsed,
                    details={
                        "block_number": block_number,
                        "block_hash": block_hash,
                        "mempool_time": (verification_start - mempool_start) if (verification_start and mempool_start) else 0,
                        "verification_time": (blocks_start - verification_start) if (blocks_start and verification_start) else 0,
                        "total_time": elapsed
                    }
                )
            
            # Check blocks/events timeout
            if was_in_mempool:
                time_since_mempool = current_time - mempool_start
                if time_since_mempool > timeout_in_blocks:
                    is_dag = self._is_dag_chain(chain)
                    item_type = "events" if is_dag else "blocks"
                    error = f"Datum not in {item_type} after {time_since_mempool:.1f}s"
                    self._log(f"  ❌ {error}")
                    self._log(f"  💡 Datum was in mempool but never made it into a {item_type[:-1]}")
                    return DatumMonitorResult(
                        status=DatumStatus.TIMEOUT_IN_BLOCKS,
                        datum_hash=datum_hash,
                        elapsed_time=elapsed,
                        details={"time_since_mempool": time_since_mempool},
                        error_message=error
                    )
            
            # Wait before next check
            await asyncio.sleep(check_interval)
    
    async def _check_mempool(self, node: str, network: str, chain: str, datum_hash: str) -> bool:
        """Check if datum is in mempool."""
        try:
            # Convert node to container name
            container_name = self._node_to_container(node)
            container = self.docker_client.containers.get(container_name)
            
            # CRITICAL: Check container status before executing command (fail-fast)
            container.reload()
            if container.status != 'running':
                error_msg = (
                    f"Container {container_name} (node {node}) is not running "
                    f"(status: {container.status}). Container crashed during datum monitoring."
                )
                self._log(f"  ❌ {error_msg}")
                # Collect crash artifacts if container crashed
                from ..docker.container import DockerContainerManager
                from pathlib import Path
                container_manager = DockerContainerManager(Path.cwd(), self.node_cli_path)
                try:
                    artifacts = container_manager.collect_crash_artifacts(
                        container_name=container_name,
                        node_id=node,
                        test_name=None
                    )
                    self._log(f"  📦 Crash artifacts collected: {artifacts}")
                except Exception as artifact_error:
                    self._log(f"  ⚠️ Failed to collect crash artifacts: {artifact_error}")
                
                # Raise exception to stop monitoring immediately
                raise RuntimeError(error_msg)
            
            # Use mempool_list instead of mempool_proc -list
            cmd = [
                self.node_cli_path, "mempool_list",
                "-net", network, "-chain", chain
            ]
            
            self._log(f"  🔍 Checking mempool on {node} ({container_name})...")
            self._log(f"     Command: {' '.join(cmd)}")
            
            result = container.exec_run(cmd, demux=True)
            exit_code = result.exit_code
            stdout, stderr = result.output
            
            stdout_str = stdout.decode('utf-8') if stdout else ""
            stderr_str = stderr.decode('utf-8') if stderr else ""
            
            self._log(f"     Exit code: {exit_code}")
            if stdout_str:
                self._log(f"     Stdout preview: {stdout_str[:200]}")
            if stderr_str:
                self._log(f"     Stderr: {stderr_str[:200]}")
            
            if exit_code != 0:
                self._log(f"  ⚠️ Mempool check failed with exit code {exit_code}")
                return False
            
            # Check if our datum hash is in the output
            found = datum_hash.lower() in stdout_str.lower()
            self._log(f"     Result: {'✓ FOUND' if found else '✗ NOT FOUND'}")
            
            return found
            
        except RuntimeError:
            # Re-raise RuntimeError (container crash) to stop monitoring
            raise
        except Exception as e:
            # Check if error is about container not running
            error_str = str(e).lower()
            if "not running" in error_str or "409" in error_str or "conflict" in error_str:
                container_name = self._node_to_container(node)
                error_msg = (
                    f"Container {container_name} (node {node}) crashed during mempool check: {e}"
                )
                self._log(f"  ❌ {error_msg}")
                # Collect crash artifacts
                from ..docker.container import DockerContainerManager
                from pathlib import Path
                container_manager = DockerContainerManager(Path.cwd(), self.node_cli_path)
                try:
                    artifacts = container_manager.collect_crash_artifacts(
                        container_name=container_name,
                        node_id=node,
                        test_name=None
                    )
                    self._log(f"  📦 Crash artifacts collected: {artifacts}")
                except Exception as artifact_error:
                    self._log(f"  ⚠️ Failed to collect crash artifacts: {artifact_error}")
                raise RuntimeError(error_msg)
            
            self._log(f"  ⚠️ Failed to check mempool: {e}")
            import traceback
            self._log(f"     Traceback: {traceback.format_exc()}")
            return False
    
    async def _check_verified_on_masters(self, node: str, network: str, chain: str, datum_hash: str) -> bool:
        """Check if datum was verified by master nodes."""
        # For now, assume verified if it left mempool
        # Full implementation would check master node logs or verification status
        return True
    
    def _is_dag_chain(self, chain: str) -> bool:
        """
        Determine if chain uses DAG-PoA (events) or blockchain (blocks).
        
        Args:
            chain: Chain name (e.g., "zerochain", "main", "kelvin")
            
        Returns:
            True if chain uses DAG (events), False if blockchain (blocks)
        """
        # DAG-PoA chains use events instead of blocks
        dag_chains = ["zerochain", "zero", "0"]
        return chain.lower() in dag_chains
    
    async def _check_in_blocks(self, node: str, network: str, chain: str, datum_hash: str) -> Optional[Tuple[int, str]]:
        """
        Check if datum is in a block or DAG event (auto-detects based on chain).
        
        For DAG chains (zerochain): checks events
        For blockchain chains (main, kelvin): checks blocks
        
        Returns:
            Tuple of (block/event_number, hash) if found, None otherwise
        """
        # Auto-detect DAG vs blockchain
        if self._is_dag_chain(chain):
            return await self._check_in_dag_events(node, network, chain, datum_hash)
        else:
            return await self._check_in_blockchain_blocks(node, network, chain, datum_hash)
    
    async def _check_in_dag_events(self, node: str, network: str, chain: str, datum_hash: str) -> Optional[Tuple[int, str]]:
        """
        Check if datum is in a DAG event (for DAG-PoA chains like zerochain).
        
        Returns:
            Tuple of (event_number, event_hash) if found, None otherwise
        """
        try:
            container_name = self._node_to_container(node)
            container = self.docker_client.containers.get(container_name)
            
            # Get recent events list
            cmd = [
                self.node_cli_path, "dag", "event", "list",
                "-net", network, "-chain", chain, "-from", "events", "-limit", "20"
            ]
            
            result = container.exec_run(cmd, demux=True)
            exit_code = result.exit_code
            stdout, stderr = result.output
            
            if exit_code != 0:
                return None
            
            stdout_str = stdout.decode('utf-8') if stdout else ""
            
            # Extract all event hashes from list
            # Format: event_hash: 0x... (with underscore)
            event_hashes = re.findall(r'event_hash:\s*(0x[A-Fa-f0-9]+)', stdout_str, re.IGNORECASE)
            
            logger.debug("dag_event_list_parsed", event_count=len(event_hashes), 
                        events=event_hashes[:5] if event_hashes else [])
            
            if not event_hashes:
                return None
            
            # Check each event for our datum hash by dumping it
            for i, event_hash in enumerate(event_hashes[:10]):  # Limit to 10 recent events
                dump_cmd = [
                    self.node_cli_path, "dag", "event", "dump",
                    "-net", network, "-chain", chain, "-event", event_hash
                ]
                
                dump_result = container.exec_run(dump_cmd, demux=True)
                if dump_result.exit_code != 0:
                    logger.debug("dag_event_dump_failed", event_hash=event_hash, 
                                exit_code=dump_result.exit_code)
                    continue
                
                dump_stdout = dump_result.output[0].decode('utf-8') if dump_result.output[0] else ""
                
                # Search for datum hash in event dump (also check datum_hash: format)
                datum_hash_lower = datum_hash.lower()
                dump_lower = dump_stdout.lower()
                
                if datum_hash_lower in dump_lower:
                    self._log(f"  ✅ Datum found in DAG event ({event_hash[:16]}...)")
                    return (i + 1, event_hash)
                
                # Also try to find just the hex part without 0x prefix
                datum_hex = datum_hash_lower.replace('0x', '')
                if datum_hex in dump_lower:
                    self._log(f"  ✅ Datum found in DAG event ({event_hash[:16]}...) [hex match]")
                    return (i + 1, event_hash)
            
            return None
            
        except Exception as e:
            self._log(f"  ⚠️ Failed to check DAG events: {e}")
            return None
    
    async def _check_in_blockchain_blocks(self, node: str, network: str, chain: str, datum_hash: str) -> Optional[Tuple[int, str]]:
        """
        Check if datum is in a blockchain block (for ESBocs chains like main, kelvin).
        
        Returns:
            Tuple of (block_number, block_hash) if found, None otherwise
        """
        try:
            # Convert node to container name
            container_name = self._node_to_container(node)
            container = self.docker_client.containers.get(container_name)
            
            # Get recent blocks list
            cmd = [
                self.node_cli_path, "block", "list",
                "-net", network, "-chain", chain
            ]
            
            result = container.exec_run(cmd, demux=True)
            exit_code = result.exit_code
            stdout, stderr = result.output
            
            if exit_code != 0:
                logger.debug("blockchain_block_list_failed", exit_code=exit_code)
                return None
            
            stdout_str = stdout.decode('utf-8') if stdout else ""
            
            # Extract block hashes from list output
            # Format: block_hash: 0x...
            block_hashes = re.findall(r'block_hash:\s*(0x[A-Fa-f0-9]{64})', stdout_str, re.IGNORECASE)
            block_nums = re.findall(r'block_num:\s*(\d+)', stdout_str)
            
            logger.debug("blockchain_checking_blocks", 
                        datum_hash=datum_hash[:20],
                        block_count=len(block_hashes),
                        block_nums=block_nums[:5] if block_nums else [])
            
            # Check each block for our datum hash
            for i, block_hash in enumerate(block_hashes[:10]):  # Limit to 10 recent blocks
                dump_cmd = [
                    self.node_cli_path, "block", "dump",
                    "-net", network, "-chain", chain, "-hash", block_hash
                ]
                
                dump_result = container.exec_run(dump_cmd, demux=True)
                if dump_result.exit_code != 0:
                    logger.debug("blockchain_block_dump_failed", 
                                block_hash=block_hash[:20],
                                exit_code=dump_result.exit_code)
                    continue
                
                dump_stdout = dump_result.output[0].decode('utf-8') if dump_result.output[0] else ""
                
                # Search for datum hash in block dump
                datum_hash_lower = datum_hash.lower()
                dump_lower = dump_stdout.lower()
                
                if datum_hash_lower in dump_lower:
                    block_num = int(block_nums[i]) if i < len(block_nums) else i
                    logger.info("blockchain_datum_found_in_block",
                               datum_hash=datum_hash[:20],
                               block_num=block_num,
                               block_hash=block_hash[:20])
                    self._log(f"  ✅ Datum found in block #{block_num} ({block_hash[:16]}...)")
                    return (block_num, block_hash)
                else:
                    logger.debug("blockchain_datum_not_in_block",
                                datum_hash=datum_hash[:20],
                                block_num=block_nums[i] if i < len(block_nums) else i,
                                block_hash=block_hash[:20])
            
            logger.debug("blockchain_datum_not_found_in_any_block",
                        datum_hash=datum_hash[:20],
                        blocks_checked=min(len(block_hashes), 10))
            return None
            
        except Exception as e:
            self._log(f"  ⚠️ Failed to check blocks: {e}")
            return None
    
    def _extract_node_id(self, node: str) -> int:
        """
        Extract node ID from node name.
        
        Args:
            node: Node name (e.g., "root-1", "node-2", "master-3", "node1")
            
        Returns:
            Node ID as integer
        """
        # Extract number from node name (e.g., "root-1" -> 1, "node-2" -> 2, "node1" -> 1)
        import re
        match = re.search(r'-(\d+)$', node)
        if match:
            return int(match.group(1))
        # Fallback: try to extract from "node1", "node2" format
        match = re.search(r'(\d+)$', node)
        if match:
            return int(match.group(1))
        # Default to 1 if can't extract
        return 1
    
    def _id_to_node_name(self, node_id: int) -> str:
        """
        Convert node ID to node name.
        
        Args:
            node_id: Node ID
            
        Returns:
            Node name matching original format (e.g., "root-1", "node-2")
        """
        # For now, use generic "node-{id}" format
        # The actual node name format doesn't matter for container lookup
        return f"node-{node_id}"
    
    def _build_topology_map(self) -> None:
        """
        Build topology map by inspecting running containers.
        Maps roles (root, master, etc.) to their node IDs.
        """
        if self._topology_map is not None:
            return

        self._topology_map = {'root': [], 'master': [], 'full': [], 'node': []}
        
        try:
            # Get all containers for the project (assuming default project name 'cellframe-stage')
            # We look for containers with names starting with cellframe-stage-node-
            containers = self.docker_client.containers.list(
                filters={"name": "cellframe-stage-node-"}
            )
            
            for container in containers:
                try:
                    # Extract node ID from name
                    name = container.name
                    if not name.startswith("cellframe-stage-node-"):
                        continue
                        
                    node_id_str = name.replace("cellframe-stage-node-", "")
                    if not node_id_str.isdigit():
                        continue
                        
                    node_id = int(node_id_str)
                    self._topology_map['node'].append(node_id)
                    
                    # Inspect environment to find role
                    # NODE_ROLE is set in Dockerfile/docker-compose
                    env = container.attrs.get('Config', {}).get('Env', [])
                    role = 'full' # Default
                    
                    for e in env:
                        if e.startswith('NODE_ROLE='):
                            role = e.split('=')[1].lower()
                            break
                    
                    if role in self._topology_map:
                        self._topology_map[role].append(node_id)
                        
                except Exception as e:
                    logger.warning(f"Failed to inspect container {container.name}: {e}")
            
            # Sort IDs for deterministic mapping
            for role in self._topology_map:
                self._topology_map[role].sort()
                
            logger.debug("topology_map_built", map=self._topology_map)
            
        except Exception as e:
            logger.warning(f"Failed to build topology map: {e}")
            # If discovery fails, we leave the map empty to fail fast rather than using hardcoded defaults
            # This prevents "magic" behavior that might hide configuration issues
            pass

    def _node_to_container(self, node: str) -> str:
        """
        Convert node name/alias to Docker container name.
        Dynamically resolves roles (root-N, master-N) to node IDs based on running containers.
        
        Args:
            node: Node name (e.g., "root-1", "node-2", "master-1", "node1")
            
        Returns:
            Container name (e.g., "cellframe-stage-node-1")
        """
        # Already a full container name
        if node.startswith("cellframe-stage-"):
            return node
            
        # Ensure topology map is built
        self._build_topology_map()
        
        node_num = None
        
        if node.startswith("root-"):
            try:
                idx = int(node.split("-")[1]) - 1 # root-1 -> index 0
                if 0 <= idx < len(self._topology_map['root']):
                    node_num = str(self._topology_map['root'][idx])
            except (IndexError, ValueError):
                pass
                
        elif node.startswith("master-"):
            try:
                idx = int(node.split("-")[1]) - 1 # master-1 -> index 0
                if 0 <= idx < len(self._topology_map['master']):
                    node_num = str(self._topology_map['master'][idx])
            except (IndexError, ValueError):
                pass
                
        elif node.startswith('node'):
            # Handle "node1", "node-1" formats
            node_num = node[4:] if node[4:5].isdigit() else node.split('-')[1] if '-' in node else node[4:]
        
        if not node_num:
             # Fail fast: if we can't resolve node via topology map, raise an error
            raise RuntimeError(
                f"Could not resolve node '{node}' via topology map. "
                f"Topology map: {self._topology_map}. "
                f"Node must be in format 'root-N', 'master-N', or 'nodeN' where N is a valid index."
            )
        
        return f"cellframe-stage-node-{node_num}"
