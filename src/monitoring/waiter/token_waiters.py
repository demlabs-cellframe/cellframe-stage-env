"""
Token waiters for genesis operations.
"""

import re
import time
from typing import Callable

from ..base import BaseWaiter
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TokenInMempoolWaiter(BaseWaiter):
    """
    Wait for token to appear in mempool on zerochain.
    
    Checks multiple methods:
    1. token list command
    2. token show command
    3. DAG events (as fallback)
    
    Usage:
        waiter = TokenInMempoolWaiter(exec_cli_func, node_id, network_name, token_name="TCELL")
        await waiter.wait(timeout=60.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        node_id: int,
        network_name: str = "stagenet",
        token_name: str = "TCELL",
        chain: str = "zerochain",
        poll_interval: float = 2.0
    ):
        """
        Initialize token in mempool waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            node_id: Node ID to check
            network_name: Network name
            token_name: Token name to look for (default: TCELL)
            chain: Chain name (default: zerochain)
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.node_id = node_id
        self.network_name = network_name
        self.token_name = token_name
        self.chain = chain
        self._start_time = None
    
    async def check(self) -> bool:
        """Check if token is in mempool."""
        if self._start_time is None:
            self._start_time = time.time()
        
        elapsed = time.time() - self._start_time
        
        # Method 1: Check if TCELL token exists on zerochain using token list
        exit_code_list, stdout_list, stderr_list = self.exec_cli(
            self.node_id,
            f"token list -net {self.network_name} -chain {self.chain}",
            check_output=False
        )
        
        if exit_code_list == 0 and stdout_list:
            token_found = self.token_name in stdout_list or self.token_name.lower() in stdout_list.lower()
            if token_found:
                logger.info("tcell_token_found_on_zerochain_via_list",
                           elapsed=f"{elapsed:.1f}s",
                           token_list_output=stdout_list[:500],
                           note="TCELL token exists on zerochain, ready for transfers")
                return True
            else:
                logger.debug("tcell_not_in_token_list",
                           elapsed=f"{elapsed:.1f}s",
                           token_list_output=stdout_list[:500] if stdout_list else "empty",
                           note="TCELL not found in token list, trying alternative methods")
        else:
            logger.debug("token_list_failed",
                       elapsed=f"{elapsed:.1f}s",
                       exit_code=exit_code_list,
                       stderr=stderr_list[:200] if stderr_list else "empty",
                       note="token list command failed, trying alternative methods")
        
        # Method 2: Try token show as alternative check
        exit_code_show, stdout_show, stderr_show = self.exec_cli(
            self.node_id,
            f"token show -net {self.network_name} -chain {self.chain} -token {self.token_name}",
            check_output=False
        )
        
        if exit_code_show == 0 and stdout_show:
            token_found = self.token_name in stdout_show or self.token_name.lower() in stdout_show.lower()
            if token_found:
                logger.info("tcell_token_found_on_zerochain_via_show",
                           elapsed=f"{elapsed:.1f}s",
                           token_show_output=stdout_show[:500],
                           note="TCELL token exists on zerochain (verified via token show)")
                return True
            else:
                logger.debug("tcell_not_in_token_show",
                           elapsed=f"{elapsed:.1f}s",
                           token_show_output=stdout_show[:500] if stdout_show else "empty")
        else:
            logger.debug("token_show_failed",
                       elapsed=f"{elapsed:.1f}s",
                       exit_code=exit_code_show,
                       stderr=stderr_show[:200] if stderr_show else "empty")
        
        # Method 3: Check if zerochain DAG has events (indicates chain is loaded)
        if elapsed > 5.0:  # Only check DAG after initial wait
            exit_code_dag, stdout_dag, _ = self.exec_cli(
                self.node_id,
                f"dag event list -net {self.network_name} -chain {self.chain} -from events -limit 1",
                check_output=False
            )
            
            if exit_code_dag == 0 and stdout_dag:
                total_match = re.search(r'total_events:\s*(\d+)', stdout_dag, re.IGNORECASE)
                total_events = int(total_match.group(1)) if total_match else 0
                if total_events > 0:
                    logger.debug("zerochain_has_dag_events",
                               elapsed=f"{elapsed:.1f}s",
                               total_events=total_events,
                               note="Zerochain has DAG events, token should be accessible")
                else:
                    logger.debug("zerochain_no_dag_events",
                               elapsed=f"{elapsed:.1f}s",
                               note="Zerochain may not be fully loaded yet")
        
        return False
    
    async def wait(self, timeout: float, name: str = "token_in_mempool") -> None:
        """Wait until token is in mempool."""
        try:
            await super().wait(timeout, name)
        except TimeoutError:
            elapsed = time.time() - self._start_time
            logger.warning("token_not_found_in_mempool_timeout",
                         elapsed=f"{elapsed:.1f}s",
                         token=self.token_name,
                         chain=self.chain,
                         note="Token not found in mempool - may need more time or DAG processing")
            raise

