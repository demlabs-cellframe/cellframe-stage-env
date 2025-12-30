"""
Waiters for chain synchronization operations.

Extracted from genesis_sync.py for better code organization.
"""

import asyncio
import re
import time
from typing import List, Callable, Optional

from ..base import BaseWaiter
from ...network.models import NodeConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


class FirstBlockWaiter(BaseWaiter):
    """
    Wait for first block to be created in blockchain chain.
    
    First checks mempool, then polls 'block list' until block appears.
    Also checks network state and consensus timer status during wait.
    
    Usage:
        waiter = FirstBlockWaiter(exec_cli_func, network_name, chain_name, master_nodes)
        await waiter.wait(timeout=60.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        network_name: str = "stagenet",
        chain_name: str = "main",
        master_nodes: Optional[List[NodeConfig]] = None,
        poll_interval: float = 2.0
    ):
        """
        Initialize first block waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            network_name: Network name
            chain_name: Blockchain chain name (e.g., "main", "kelvin")
            master_nodes: Optional list of MASTER nodes for ESBocs diagnostic checks
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.network_name = network_name
        self.chain_name = chain_name
        self.master_nodes = master_nodes or []
        self._start_time = None
        self._mempool_checked = False
    
    async def check(self) -> bool:
        """Check if first block exists."""
        if self._start_time is None:
            self._start_time = time.time()
            
            # First verify TX is in mempool
            logger.info("checking_mempool_before_waiting_for_block")
            try:
                exit_code_mp, stdout_mp, _ = self.exec_cli(
                    1,
                    f"mempool_list -net {self.network_name} -chain {self.chain_name}",
                    check_output=False
                )
                logger.info("mempool_check",
                           chain=self.chain_name,
                           exit_code=exit_code_mp,
                           output_preview=stdout_mp[:200] if stdout_mp else "EMPTY")
            except Exception as e:
                logger.warning("mempool_check_failed", error=str(e)[:100])
            
            # DIAGNOSTIC: Check network state before waiting
            logger.info("diagnostic_checking_network_state_before_wait")
            try:
                exit_code_net, stdout_net, _ = self.exec_cli(
                    1,
                    f"net -net {self.network_name} get status",
                    check_output=False
                )
                if exit_code_net == 0 and stdout_net:
                    is_online = "NET_STATE_ONLINE" in stdout_net or "current: ONLINE" in stdout_net
                    logger.info("diagnostic_network_state",
                               chain=self.chain_name,
                               is_online=is_online,
                               state_preview=stdout_net[:300])
                    if not is_online:
                        logger.warning("network_not_online_during_block_wait",
                                     chain=self.chain_name,
                                     state=stdout_net[:200])
            except Exception as e:
                logger.warning("network_state_check_failed", error=str(e)[:100])
        
        # Check if block exists
        exit_code, stdout, stderr = self.exec_cli(
            1,
            f"block list -net {self.network_name} -chain {self.chain_name} -limit 1",
            check_output=False
        )
        
        if exit_code == 0 and stdout:
            # Check "have blocks: N" pattern (works for both master and release-6.0)
            blocks_match = re.search(r'have\s+blocks[:\s]+(\d+)', stdout, re.IGNORECASE)
            if blocks_match:
                block_count = int(blocks_match.group(1))
                if block_count > 0:
                    elapsed = time.time() - self._start_time
                    logger.info("first_block_created",
                               chain=self.chain_name,
                               block_count=block_count,
                               elapsed=f"{elapsed:.1f}s")
                    return True
                else:
                    # Explicitly 0 blocks
                    return False
            
            # Fallback: check for block hash in output (0x followed by 64 hex chars)
            hash_match = re.search(r'0x[A-Fa-f0-9]{64}', stdout)
            if hash_match:
                elapsed = time.time() - self._start_time
                logger.info("first_block_created_by_hash",
                           chain=self.chain_name,
                           elapsed=f"{elapsed:.1f}s",
                           hash=hash_match.group(0)[:20] + "...")
                return True
        
        return False

