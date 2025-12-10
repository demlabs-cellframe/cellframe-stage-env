"""
Datum waiters for waiting for datums to appear in mempool or chain.
"""

import re
import time
from typing import Callable

from ..base import BaseWaiter
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DatumInMempoolWaiter(BaseWaiter):
    """
    Wait for datum hash to appear in mempool.
    
    Usage:
        waiter = DatumInMempoolWaiter(exec_cli_func, node_id, datum_hash, network_name, chain="zerochain")
        await waiter.wait(timeout=30.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        datum_hash: str,
        network_name: str = "stagenet",
        chain: str = "zerochain",
        poll_interval: float = 0.5
    ):
        """
        Initialize datum in mempool waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node_id: Node ID to check
            datum_hash: Datum hash to look for
            network_name: Network name
            chain: Chain name (default: zerochain)
            poll_interval: Seconds between checks (default: 0.5s for fast detection)
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.datum_hash = datum_hash
        self.network_name = network_name
        self.chain = chain
        self._start_time = None
    
    async def check(self) -> bool:
        """Check if datum hash is in mempool."""
        if self._start_time is None:
            self._start_time = time.time()
        
        try:
            exit_code, stdout, stderr = self.exec_cli(
                self.node_id,
                f"mempool list -net {self.network_name} -chain {self.chain}",
                check_output=False
            )
            
            elapsed = time.time() - self._start_time
            
            if exit_code != 0:
                # Check if stderr indicates container crash (fail-fast)
                if stderr and ("not running" in stderr.lower() or "crashed" in stderr.lower()):
                    error_msg = f"Container crashed: {stderr}"
                    logger.error("container_crashed_during_datum_monitoring",
                               node_id=self.node_id,
                               datum=self.datum_hash[:16],
                               error=error_msg,
                               elapsed=f"{elapsed:.2f}s")
                    # Re-raise to stop monitoring immediately
                    raise RuntimeError(
                        f"Container crashed during datum monitoring (node {self.node_id}): {error_msg}"
                    )
                
                logger.warning("mempool_list_failed",
                           node_id=self.node_id,
                           exit_code=exit_code,
                           stderr=stderr[:500] if stderr else "empty",
                           elapsed=f"{elapsed:.2f}s")
                return False
            
            # Log mempool contents for debugging (first few checks only)
            if elapsed < 5.0:  # Only log during first 5 seconds
                logger.info("mempool_list_result",
                           node_id=self.node_id,
                           stdout_length=len(stdout) if stdout else 0,
                           stdout_preview=stdout[:500] if stdout else "empty",
                           looking_for=self.datum_hash,
                           elapsed=f"{elapsed:.2f}s")
            
            # Check if datum hash is in the output
            # Try both hex format (with 0x prefix) and without prefix
            datum_hash_lower = self.datum_hash.lower()
            datum_hash_no_prefix = datum_hash_lower.replace("0x", "") if datum_hash_lower.startswith("0x") else datum_hash_lower
            stdout_lower = stdout.lower() if stdout else ""
            
            # Check for hash with 0x prefix
            if datum_hash_lower in stdout_lower:
                logger.info("datum_found_in_mempool",
                           node_id=self.node_id,
                           datum=self.datum_hash[:16],
                           format="with_0x_prefix",
                           elapsed=f"{elapsed:.2f}s")
                return True
            
            # Check for hash without 0x prefix
            if datum_hash_no_prefix in stdout_lower:
                logger.info("datum_found_in_mempool",
                           node_id=self.node_id,
                           datum=self.datum_hash[:16],
                           format="without_0x_prefix",
                           elapsed=f"{elapsed:.2f}s")
                return True
            
            # Log what we're looking for vs what we found (first check only)
            if elapsed < 2.0:
                logger.info("datum_not_found_yet",
                           node_id=self.node_id,
                           looking_for=self.datum_hash,
                           looking_for_no_prefix=datum_hash_no_prefix,
                           stdout_sample=stdout_lower[:300] if stdout_lower else "empty")
            
            return False
            
        except Exception as e:
            elapsed = time.time() - self._start_time if self._start_time else 0
            error_str = str(e).lower()
            
            # Check if error is about container crash (fail-fast)
            if "not running" in error_str or "409" in error_str or "conflict" in error_str or "crashed" in error_str:
                logger.error("container_crashed_during_datum_monitoring",
                           node_id=self.node_id,
                           datum=self.datum_hash[:16],
                           error=str(e),
                           elapsed=f"{elapsed:.2f}s")
                # Re-raise to stop monitoring immediately
                raise RuntimeError(
                    f"Container crashed during datum monitoring (node {self.node_id}): {e}"
                ) from e
            
            logger.warning("datum_mempool_check_failed",
                         node_id=self.node_id,
                         datum=self.datum_hash[:16],
                         error=str(e),
                         elapsed=f"{elapsed:.2f}s")
            return False
    
    async def wait(self, timeout: float, name: str = "datum_in_mempool") -> None:
        """Wait until datum appears in mempool."""
        try:
            await super().wait(timeout, name)
        except TimeoutError:
            elapsed = time.time() - self._start_time
            logger.warning("datum_not_found_in_mempool_timeout",
                         elapsed=f"{elapsed:.1f}s",
                         datum=self.datum_hash[:16],
                         chain=self.chain,
                         note="Datum not found in mempool - may not have been created or synced")
            raise


class DatumInChainWaiter(BaseWaiter):
    """
    Wait for datum to be written to chain (NOT just finalized in mempool).
    
    CRITICAL: For snapshots to include datum, it must be in chain cell file.
    Finalized datums in mempool may not persist after snapshot restore.
    
    Usage:
        waiter = DatumInChainWaiter(exec_cli_func, node_id, datum_hash, network_name, chain="zerochain")
        await waiter.wait(timeout=60.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        datum_hash: str,
        network_name: str = "stagenet",
        chain: str = "zerochain",
        poll_interval: float = 2.0
    ):
        """
        Initialize datum in chain waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node_id: Node ID to check
            datum_hash: Datum hash to look for
            network_name: Network name
            chain: Chain name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.datum_hash = datum_hash
        self.network_name = network_name
        self.chain = chain
        self._start_time = None
    
    async def check(self) -> bool:
        """Check if datum is written to chain."""
        if self._start_time is None:
            self._start_time = time.time()
        
        try:
            elapsed = time.time() - self._start_time
            
            # Method 1: Check via ledger list coins (works for emissions and transactions)
            exit_code, stdout, stderr = self.exec_cli(
                self.node_id,
                f"ledger list coins -net {self.network_name} -chain {self.chain}",
                check_output=False
            )
            
            # Diagnostic: Log first check to see what ledger returns
            if elapsed < 5:
                logger.info("datum_in_chain_check_ledger",
                           node_id=self.node_id,
                           datum=self.datum_hash[:16],
                           exit_code=exit_code,
                           stdout_len=len(stdout) if stdout else 0,
                           stdout_preview=stdout[:500] if stdout else "EMPTY",
                           looking_for=self.datum_hash[:32])
            
            if exit_code == 0 and stdout:
                # Check if datum hash is in ledger output
                if self.datum_hash.lower() in stdout.lower():
                    logger.info("datum_found_in_chain",
                               node_id=self.node_id,
                               datum=self.datum_hash[:16],
                               method="ledger_list",
                               elapsed=f"{elapsed:.1f}s")
                    return True
            
            # Method 2: Check via dag event dump (for events only)
            exit_code2, stdout2, stderr2 = self.exec_cli(
                self.node_id,
                f"dag event dump -event {self.datum_hash} -net {self.network_name} -chain {self.chain}",
                check_output=False
            )
            
            # Diagnostic: Log first check
            if elapsed < 5:
                logger.info("datum_in_chain_check_dag_dump",
                           node_id=self.node_id,
                           datum=self.datum_hash[:16],
                           exit_code=exit_code2,
                           stdout_len=len(stdout2) if stdout2 else 0,
                           stdout_preview=stdout2[:500] if stdout2 else "EMPTY",
                           has_errors="errors" in stdout2.lower() if stdout2 else False)
            
            if exit_code2 == 0 and stdout2 and "errors" not in stdout2.lower():
                logger.info("datum_found_in_chain",
                           node_id=self.node_id,
                           datum=self.datum_hash[:16],
                           method="dag_event_dump",
                           elapsed=f"{elapsed:.1f}s")
                return True
            
            # Method 3: Check via dag event list
            exit_code3, stdout3, _ = self.exec_cli(
                self.node_id,
                f"dag event list -net {self.network_name} -chain {self.chain} -from events",
                check_output=False
            )
            
            if exit_code3 == 0 and stdout3:
                # Extract all event hashes and check
                hash_matches = re.findall(r'(0x[A-Fa-f0-9]{64})', stdout3)
                if self.datum_hash.lower() in [h.lower() for h in hash_matches]:
                    logger.info("datum_found_in_chain",
                               node_id=self.node_id,
                               datum=self.datum_hash[:16],
                               method="dag_event_list",
                               elapsed=f"{elapsed:.1f}s")
                    return True
            
            # Log progress periodically
            if elapsed > 10 and int(elapsed) % 10 == 0:
                logger.debug("datum_not_in_chain_yet",
                           node_id=self.node_id,
                           datum=self.datum_hash[:16],
                           elapsed=f"{elapsed:.1f}s",
                           methods_tried=["ledger_list", "dag_event_dump", "dag_event_list"],
                           note="Datum finalized but not yet written to chain/ledger")
            
            return False
            
        except Exception as e:
            logger.warning("datum_chain_check_failed",
                         node_id=self.node_id,
                         datum=self.datum_hash[:16],
                         error=str(e)[:200])
            return False

