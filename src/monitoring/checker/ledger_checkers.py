"""
Ledger checkers for validating transactions in ledger.

These checkers use `ledger info` command instead of `tx_history` to check
if transactions are present in ledger_items hash table. This is more reliable
than tx_history because it doesn't depend on PVT(a_dag)->datums being populated.
"""

from typing import Callable, Optional
import asyncio
from .base import BaseChecker
from ...utils.logger import get_logger
from ..waiters import NetworkOnlineWaiter

logger = get_logger(__name__)


class LedgerTransactionChecker(BaseChecker):
    """
    Checks if a transaction (datum) is present in ledger using `ledger info`.
    
    This checker uses `ledger info -hash <datum_hash>` which checks ledger_items
    directly, unlike tx_history which depends on PVT(a_dag)->datums being populated.
    
    Usage:
        checker = LedgerTransactionChecker(
            exec_cli_func, node_id, datum_hash, network="stagenet"
        )
        await checker.verify()  # Raises RuntimeError if transaction not found
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        datum_hash: str,
        network: str = "stagenet",
    ):
        """
        Initialize ledger transaction checker.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node_id: Node ID to check
            datum_hash: Datum hash (transaction hash) to check
            network: Network name
        """
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.datum_hash = datum_hash
        self.network = network
    
    async def check(self) -> bool:
        """
        Check if transaction is present in ledger.
        
        Returns:
            True if transaction found in ledger, False otherwise
        """
        try:
            exit_code, stdout, stderr = self.exec_cli(
                self.node_id,
                f"ledger info -net {self.network} -hash {self.datum_hash}",
                check_output=False
            )
            
            if exit_code != 0:
                logger.debug(
                    "ledger_info_check_failed",
                    node_id=self.node_id,
                    datum_hash=self.datum_hash[:16],
                    exit_code=exit_code,
                    stderr=stderr[:200] if stderr else "empty",
                    note="ledger info command failed"
                )
                return False
            
            # Check if datum hash is present in output
            # ledger info returns transaction details if found
            if stdout and self.datum_hash.lower() in stdout.lower():
                # Also check for "Datum_tx_hash" or similar indicators
                if "Datum_tx_hash" in stdout or "datum" in stdout.lower():
                    logger.debug(
                        "ledger_transaction_found",
                        node_id=self.node_id,
                        datum_hash=self.datum_hash[:16],
                        note="Transaction found in ledger"
                    )
                    return True
            
            logger.debug(
                "ledger_transaction_not_found",
                node_id=self.node_id,
                datum_hash=self.datum_hash[:16],
                stdout=stdout[:500] if stdout else "empty",
                note="Transaction not found in ledger output"
            )
            return False
            
        except Exception as e:
            logger.warning(
                "ledger_check_exception",
                node_id=self.node_id,
                datum_hash=self.datum_hash[:16],
                error=str(e)[:200],
                note="Exception during ledger check"
            )
            return False
    
    async def verify(self) -> None:
        """
        Verify transaction is in ledger, raise exception if not found.
        
        Raises:
            RuntimeError: If transaction not found in ledger
        """
        if not await self.check():
            raise RuntimeError(
                f"Transaction {self.datum_hash[:16]}... not found in ledger "
                f"on node {self.node_id} (network: {self.network})"
            )


async def ensure_network_ready_for_utxo(
    exec_cli: Callable,
    node_id: int,
    network: str = "stagenet",
    timeout: float = 60.0
) -> None:
    """
    Ensure network is ready for UTXO operations (workaround for old node versions).
    
    This function checks network state and triggers sync if needed to ensure
    wallet cache is loaded. This is a workaround for nodes that don't have
    the SDK fix that loads wallet cache after chain loading.
    
    Args:
        exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
        node_id: Node ID to check
        network: Network name
        timeout: Maximum time to wait for network to become ready
        
    Raises:
        RuntimeError: If network doesn't become ready within timeout
    """
    try:
        # Check current network state
        exit_code, stdout, stderr = exec_cli(
            node_id,
            f"net -net {network} get status",
            check_output=False
        )
        
        if exit_code != 0:
            logger.warning(
                "network_status_check_failed",
                node_id=node_id,
                exit_code=exit_code,
                stderr=stderr[:200] if stderr else "empty",
                note="Failed to check network status, proceeding anyway"
            )
            return
        
        # If network is already ONLINE, no action needed
        if stdout and "NET_STATE_ONLINE" in stdout:
            logger.debug(
                "network_already_online",
                node_id=node_id,
                note="Network is already ONLINE, no sync needed"
            )
            return
        
        # If network is OFFLINE, trigger sync to load wallet cache
        if stdout and "NET_STATE_OFFLINE" in stdout:
            logger.info(
                "network_offline_triggering_sync",
                node_id=node_id,
                note="Network is OFFLINE, triggering sync to load wallet cache"
            )
            
            # Trigger sync
            exit_code_sync, stdout_sync, stderr_sync = exec_cli(
                node_id,
                f"net -net {network} go sync",
                check_output=False
            )
            
            if exit_code_sync != 0:
                logger.warning(
                    "network_sync_trigger_failed",
                    node_id=node_id,
                    exit_code=exit_code_sync,
                    stderr=stderr_sync[:200] if stderr_sync else "empty",
                    note="Failed to trigger network sync, wallet cache may not be loaded"
                )
                return
            
            # Wait for network to become ONLINE
            waiter = NetworkOnlineWaiter(exec_cli, node_id, network)
            try:
                await waiter.wait(timeout=timeout, name="network_online_for_utxo")
                logger.info(
                    "network_ready_for_utxo",
                    node_id=node_id,
                    note="Network is now ONLINE, wallet cache should be loaded"
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "network_online_timeout",
                    node_id=node_id,
                    timeout=timeout,
                    note="Network did not become ONLINE within timeout, wallet cache may not be loaded"
                )
                # Don't raise - allow fallback to ledger to work
        
    except Exception as e:
        logger.warning(
            "ensure_network_ready_exception",
            node_id=node_id,
            error=str(e)[:200],
            note="Exception during network readiness check, proceeding anyway"
        )
        # Don't raise - allow fallback to ledger to work

