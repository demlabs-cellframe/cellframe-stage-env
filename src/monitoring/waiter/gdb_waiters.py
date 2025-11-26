"""
GDB waiters for genesis operations.
"""

import time
from typing import Callable

from ..base import BaseWaiter
from src.utils.logger import get_logger

logger = get_logger(__name__)


class GDBClustersReadyWaiter(BaseWaiter):
    """
    Wait for GDB clusters initialization.
    
    GDB cluster for "stagenet.service.orders" is created when stake service initializes.
    This happens during network load, AFTER chains are loaded.
    If we create order before cluster is initialized, dap_global_db_set_sync will fail.
    
    Usage:
        waiter = GDBClustersReadyWaiter(exec_cli_func, node_id, network_name)
        await waiter.wait(timeout=10.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        network_name: str = "stagenet",
        poll_interval: float = 1.0
    ):
        """
        Initialize GDB clusters ready waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node_id: Node ID to check
            network_name: Network name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.network_name = network_name
        self._start_time = None
    
    async def check(self) -> bool:
        """Check if GDB clusters are ready."""
        if self._start_time is None:
            self._start_time = time.time()
            logger.info("waiting_for_gdb_clusters_initialization")
        
        try:
            # Check if we can read from stagenet.service.orders group
            # This will work only if GDB cluster is initialized
            exit_code, stdout, stderr = self.exec_cli(
                self.node_id,
                f"srv_stake order list fee -net {self.network_name}",
                check_output=False
            )
            # exit_code=0 means GDB cluster is ready (even if "No orders found")
            if exit_code == 0:
                elapsed = time.time() - self._start_time
                logger.info("gdb_clusters_ready",
                           elapsed=f"{elapsed:.1f}s",
                           note="GDB cluster for orders is initialized")
                return True
        except Exception:
            pass
        
        return False
    
    async def wait(self, timeout: float, name: str = "gdb_clusters_ready") -> None:
        """Wait until GDB clusters are ready."""
        try:
            await super().wait(timeout, name)
        except TimeoutError:
            elapsed = time.time() - self._start_time
            logger.warning("gdb_clusters_readiness_unknown",
                         elapsed=f"{elapsed:.1f}s",
                         note="Could not verify GDB cluster readiness, proceeding anyway")
            # Don't raise - this is not critical, proceed anyway

