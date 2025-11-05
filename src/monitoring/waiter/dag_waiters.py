"""
DAG event waiters for genesis operations.
"""

import re
import time
from typing import Callable

from ..base import BaseWaiter
from ...utils.logger import get_logger

logger = get_logger(__name__)


class DAGEventWaiter(BaseWaiter):
    """
    Wait for specific datum hash to appear in DAG events.
    
    Checks DAG events and event dumps to find specific datum hash.
    
    Usage:
        waiter = DAGEventWaiter(exec_cli_func, node_id, datum_hash, network_name, chain="zerochain")
        await waiter.wait(timeout=120.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        datum_hash: str,
        network_name: str = "stagenet",
        chain: str = "zerochain",
        poll_interval: float = 5.0
    ):
        """
        Initialize DAG event waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node_id: Node ID to check
            datum_hash: Datum hash to look for
            network_name: Network name
            chain: Chain name (default: zerochain)
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.datum_hash = datum_hash
        self.network_name = network_name
        self.chain = chain
        self._start_time = None
        self._last_log_time = None
    
    async def check(self) -> bool:
        """Check if datum hash is in DAG events."""
        if self._start_time is None:
            self._start_time = time.time()
            self._last_log_time = self._start_time
        
        # For DAG-PoA, check if datum is in events (not blocks!)
        exit_code, stdout_events_str, _ = self.exec_cli(
            self.node_id,
            f"dag event list -net {self.network_name} -chain {self.chain} -from events -limit 20",
            check_output=False
        )
        
        # Log progress every 10 seconds
        elapsed = time.time() - self._start_time
        if elapsed - (self._last_log_time or 0) >= 10:
            logger.info("dag_finalization_progress", 
                       datum=self.datum_hash[:16],
                       elapsed=f"{elapsed:.1f}s",
                       event_list_preview=stdout_events_str[:300] if stdout_events_str else "empty",
                       exit_code=exit_code)
            self._last_log_time = time.time()
        
        # CRITICAL: Check if THIS SPECIFIC datum hash is in DAG events
        # Not just "total events > 0" - we need to verify the specific datum is there
        if exit_code == 0 and stdout_events_str:
            # Parse event hashes from output
            event_hashes = re.findall(r'hash:\s*(0x[A-Fa-f0-9]{64})', stdout_events_str, re.IGNORECASE)
            total_match = re.search(r'total events:\s*(\d+)', stdout_events_str, re.IGNORECASE)
            total_events = int(total_match.group(1)) if total_match else 0
            
            # Check each event for our datum hash
            datum_found = False
            for evt_hash in event_hashes:
                exit_code_dump, stdout_dump, _ = self.exec_cli(
                    self.node_id,
                    f"dag event dump -net {self.network_name} -chain {self.chain} -event {evt_hash} -from events",
                    check_output=False
                )
                if exit_code_dump == 0 and stdout_dump:
                    # Check if our datum hash is in this event
                    if self.datum_hash.lower() in stdout_dump.lower():
                        datum_found = True
                        logger.info("datum_found_in_dag_event",
                                   datum=self.datum_hash[:16],
                                   event_hash=evt_hash[:16],
                                   total_events=total_events,
                                   elapsed=f"{elapsed:.1f}s")
                        break
            
            if datum_found:
                logger.info("datum_finalized_in_dag", 
                           datum=self.datum_hash[:16],
                           total_events=total_events,
                           elapsed=f"{elapsed:.1f}s")
                return True
        
        return False
    
    async def wait(self, timeout: float, name: str = "dag_event") -> None:
        """Wait until datum hash appears in DAG events."""
        try:
            await super().wait(timeout, name)
        except TimeoutError:
            # CRITICAL: Final diagnostic - check mempool and event contents
            logger.error("datum_not_finalized_diagnostic",
                        datum=self.datum_hash[:16],
                        elapsed=timeout,
                        note="Datum not finalized - collecting diagnostic information")
            
            # Check mempool one more time
            exit_code_mempool_final, stdout_mempool_final, _ = self.exec_cli(
                self.node_id,
                f"mempool list -net {self.network_name} -chain {self.chain}",
                check_output=False
            )
            logger.error("final_mempool_check",
                        datum=self.datum_hash[:16],
                        exit_code=exit_code_mempool_final,
                        mempool_content=stdout_mempool_final[:1000] if stdout_mempool_final else "empty",
                        datum_in_mempool=self.datum_hash.lower() in (stdout_mempool_final.lower() if stdout_mempool_final else ""))
            
            # Check all events content
            exit_code_events_final, stdout_events_final, _ = self.exec_cli(
                self.node_id,
                f"dag event list -net {self.network_name} -chain {self.chain} -from events -limit 20",
                check_output=False
            )
            logger.error("final_dag_events_check",
                        datum=self.datum_hash[:16],
                        exit_code=exit_code_events_final,
                        events_content=stdout_events_final[:2000] if stdout_events_final else "empty")
            
            raise RuntimeError(
                f"Datum {self.datum_hash[:16]} not finalized in DAG events after {timeout}s. "
                f"Check node logs for datum processing errors or DAG-PoA consensus issues. "
                f"Diagnostic information logged above."
            )

