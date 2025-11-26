"""
Emission waiters for genesis operations.
"""

import re
import time
from typing import Callable, List

from ..base import BaseWaiter
from ...network.models import NodeConfig
from src.utils.logger import get_logger

logger = get_logger(__name__)


class EmissionSyncedInLedgerWaiter(BaseWaiter):
    """
    Wait for emission to be synced in ledger on all nodes.
    
    Checks multiple methods:
    1. ledger list coins (may show emission hash)
    2. DAG events and event dump (as fallback)
    
    Usage:
        waiter = EmissionSyncedInLedgerWaiter(exec_cli_func, nodes, emission_hash, network_name)
        await waiter.wait(timeout=120.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        nodes: List[NodeConfig],
        emission_hash: str,
        network_name: str = "stagenet",
        chain: str = "zerochain",
        poll_interval: float = 2.0
    ):
        """
        Initialize emission synced in ledger waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            nodes: List of nodes to check
            emission_hash: Emission hash to look for
            network_name: Network name
            chain: Chain name (default: zerochain)
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.nodes = nodes
        self.emission_hash = emission_hash
        self.network_name = network_name
        self.chain = chain
        self._start_time = None
    
    async def check(self) -> bool:
        """Check if emission is synced in ledger on all nodes."""
        if self._start_time is None:
            self._start_time = time.time()
        
        all_nodes_have_emission = True
        for root_node in self.nodes:
            # Try multiple methods to check if emission is in ledger
            # Method 1: Check ledger list coins (may show emission hash)
            exit_code, stdout, stderr = self.exec_cli(
                root_node.node_id,
                f"ledger list coins -net {self.network_name} -chain {self.chain}",
                check_output=False
            )
            
            emission_visible = False
            if exit_code == 0 and stdout:
                # Check if emission hash is in ledger output
                emission_visible = self.emission_hash.lower() in stdout.lower()
                if not emission_visible:
                    # Method 2: Try to find event containing emission and check its datum
                    # Get event hash from DAG events
                    exit_code_events, stdout_events, _ = self.exec_cli(
                        root_node.node_id,
                        f"dag event list -net {self.network_name} -chain {self.chain} -from events -limit 10",
                        check_output=False
                    )
                    if exit_code_events == 0 and stdout_events:
                        event_hashes = re.findall(r'hash:\s*(0x[A-Fa-f0-9]{64})', stdout_events, re.IGNORECASE)
                        # Check each event for emission datum
                        for evt_hash in event_hashes:
                            exit_code_dump, stdout_dump, _ = self.exec_cli(
                                root_node.node_id,
                                f"dag event dump -net {self.network_name} -chain {self.chain} -event {evt_hash} -from events",
                                check_output=False
                            )
                            if exit_code_dump == 0 and stdout_dump:
                                # Check if emission hash is in event dump
                                if self.emission_hash.lower() in stdout_dump.lower():
                                    # Check if event contains "Token Emission" datum type
                                    if "Token Emission" in stdout_dump or "emission" in stdout_dump.lower():
                                        emission_visible = True
                                        logger.debug("emission_found_in_dag_event_dump",
                                                   node_id=root_node.node_id,
                                                   emission=self.emission_hash[:16],
                                                   event_hash=evt_hash[:16],
                                                   note="Emission datum found in DAG event, verifying ledger processing")
                                        break
            
            if not emission_visible:
                all_nodes_have_emission = False
                break
        
        if all_nodes_have_emission:
            elapsed = time.time() - self._start_time
            logger.info("emission_synced_in_ledger_on_all_nodes",
                       emission=self.emission_hash[:16],
                       elapsed=f"{elapsed:.1f}s",
                       nodes=len(self.nodes))
            return True
        
        return False
    
    async def wait(self, timeout: float, name: str = "emission_synced_in_ledger") -> None:
        """Wait until emission is synced in ledger on all nodes."""
        try:
            await super().wait(timeout, name)
        except TimeoutError:
            # Log detailed diagnostic info before raising error
            logger.error("emission_not_synced_in_ledger_diagnostic",
                       emission=self.emission_hash[:16],
                       timeout=timeout,
                       note="Emission not found in ledger. Collecting diagnostic information.")
            
            for root_node in self.nodes:
                # Get ledger list coins output
                exit_code, stdout, stderr = self.exec_cli(
                    root_node.node_id,
                    f"ledger list coins -net {self.network_name} -chain {self.chain}",
                    check_output=False
                )
                logger.debug("ledger_list_coins_diagnostic",
                           node_id=root_node.node_id,
                           exit_code=exit_code,
                           stdout_preview=stdout[:500] if stdout else "empty",
                           stderr_preview=stderr[:200] if stderr else "none")
                
                # Get DAG events
                exit_code_events, stdout_events, _ = self.exec_cli(
                    root_node.node_id,
                    f"dag event list -net {self.network_name} -chain {self.chain} -from events -limit 10",
                    check_output=False
                )
                logger.debug("dag_events_diagnostic",
                           node_id=root_node.node_id,
                           exit_code=exit_code_events,
                           stdout_preview=stdout_events[:500] if stdout_events else "empty")
            
            raise RuntimeError(
                f"Emission {self.emission_hash[:16]} not found in {self.chain} ledger on any root node after {timeout}s. "
                f"Emission was finalized in DAG but not processed into ledger. "
                f"This indicates a critical issue - emission datum is in DAG events but not accessible in ledger. "
                f"Cannot proceed with token transfer from emission as SDK requires emission in ledger. "
                f"Check node logs for datum processing errors or ledger loading issues. "
                f"Diagnostic information logged above."
            )

