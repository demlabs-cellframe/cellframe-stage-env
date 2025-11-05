"""
ESBocs waiters for genesis operations.
"""

import re
import time
from typing import Callable

from ..base import BaseWaiter
from ...utils.logger import get_logger

logger = get_logger(__name__)


class ESBocsActiveWaiter(BaseWaiter):
    """
    Wait for ESBocs consensus to become active (round_id > 0).
    
    Used for waiting when ESBocs needs time to synchronize validators.
    
    Usage:
        waiter = ESBocsActiveWaiter(exec_cli_func, node_id, network_name, chain="main")
        await waiter.wait(timeout=60.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        network_name: str = "stagenet",
        chain: str = "main",
        poll_interval: float = 3.0
    ):
        """
        Initialize ESBocs active waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node_id: Node ID to check
            network_name: Network name
            chain: Chain name (default: main)
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.network_name = network_name
        self.chain = chain
        self._start_time = None
    
    async def check(self) -> bool:
        """Check if ESBocs consensus is active."""
        if self._start_time is None:
            self._start_time = time.time()
        
        try:
            exit_code_esbocs, stdout_esbocs, stderr_esbocs = self.exec_cli(
                self.node_id,
                f"esbocs status -net {self.network_name} -chain {self.chain}",
                check_output=False
            )
            
            if exit_code_esbocs == 0 and stdout_esbocs:
                round_match = re.search(r'round_id:\s*(\d+)', stdout_esbocs, re.IGNORECASE)
                if round_match:
                    round_id = int(round_match.group(1))
                    if round_id > 0:
                        elapsed = time.time() - self._start_time
                        logger.info("esbocs_became_active_during_wait",
                                   round_id=round_id,
                                   elapsed=f"{elapsed:.1f}s",
                                   node_id=self.node_id)
                        return True
                    else:
                        elapsed = time.time() - self._start_time
                        logger.debug("still_waiting_for_esbocs_synchronization",
                                    elapsed=f"{elapsed:.1f}s",
                                    round_id=round_id,
                                    node_id=self.node_id)
        except Exception as e:
            elapsed = time.time() - self._start_time
            logger.debug("esbocs_status_check_exception_during_wait",
                       error=str(e)[:100],
                       elapsed=f"{elapsed:.1f}s")
        
        return False
    
    async def wait(self, timeout: float, name: str = "esbocs_active") -> None:
        """Wait until ESBocs consensus becomes active."""
        try:
            await super().wait(timeout, name)
        except TimeoutError:
            elapsed = time.time() - self._start_time
            logger.error("esbocs_not_active_after_wait",
                       node_id=self.node_id,
                       elapsed=f"{elapsed:.1f}s",
                       note="Validators may not have synchronized - check network links and START_SYNC messages")
            raise RuntimeError(
                f"ESBocs consensus did not become active on node {self.node_id} after {timeout}s. "
                f"Validators may not have synchronized - check network links and START_SYNC messages."
            )

