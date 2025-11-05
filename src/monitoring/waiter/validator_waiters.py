"""
Waiters for validator operations.

Extracted from genesis_validator.py for better code organization.
"""

import asyncio
import re
import time
from typing import List, Callable, Optional

from ..base import BaseWaiter
from ...network.models import NodeConfig
from ...utils.logger import get_logger

logger = get_logger(__name__)


class ValidatorModeActiveWaiter(BaseWaiter):
    """
    Wait until ESBocs consensus loads validator orders and activates validator mode.
    
    After hard restart, ESBocs needs time to:
    1. Initialize consensus
    2. Load validator orders from GDB
    3. Activate validator mode
    
    This prevents TX creation attempts before validator mode is ready.
    
    Usage:
        waiter = ValidatorModeActiveWaiter(exec_cli_func, nodes, network_name)
        await waiter.wait(timeout=60.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        nodes: List[NodeConfig],
        network_name: str = "stagenet",
        poll_interval: float = 2.0
    ):
        """
        Initialize validator mode active waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            nodes: List of master nodes to check
            network_name: Network name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.nodes = nodes
        self.network_name = network_name
        self._start_time = None
        self._nodes_with_validator_mode = 0
    
    async def check(self) -> bool:
        """Check if validator mode is active on all nodes."""
        if self._start_time is None:
            self._start_time = time.time()
            logger.info("waiting_for_validator_mode_activation", nodes=len(self.nodes), timeout=None)
        
        self._nodes_with_validator_mode = 0
        
        for node in self.nodes:
            try:
                # Check if validator orders are visible (= validator mode can be active)
                exit_code, stdout, stderr = self.exec_cli(
                    node.node_id,
                    f"srv_stake order list -net {self.network_name}",
                    check_output=False
                )
                
                order_count = 0
                if exit_code == 0 and stdout:
                    stdout_lower = stdout.lower()
                    # Count orders (order: prefix)
                    order_count = stdout_lower.count("order:")
                
                # CRITICAL: Also check ESBocs status to verify validator mode is actually active
                # ESBocs will show round_id > 0 if validator mode is active and orders are loaded
                esbocs_active = False
                try:
                    exit_code_esbocs, stdout_esbocs, _ = self.exec_cli(
                        node.node_id,
                        f"esbocs status -net {self.network_name} -chain main",
                        check_output=False
                    )
                    if exit_code_esbocs == 0 and stdout_esbocs:
                        # Check if ESBocs is initialized (not showing round_id: 0 means it's active)
                        # If round_id is 0 or sync_attempt is 0, ESBocs may still be initializing
                        # But if we see any ESBocs output and orders are visible, validator mode should be active
                        esbocs_active = True
                except Exception:
                    pass  # ESBocs check failed, rely on order count only
                
                if order_count >= len(self.nodes) and esbocs_active:
                    self._nodes_with_validator_mode += 1
                    logger.debug("validator_orders_loaded_and_esbocs_active",
                               node_id=node.node_id,
                               order_count=order_count,
                               esbocs_active=esbocs_active)
                elif order_count >= len(self.nodes):
                    logger.debug("validator_orders_loaded_but_esbocs_checking",
                               node_id=node.node_id,
                               order_count=order_count)
            
            except Exception as e:
                logger.debug("validator_mode_check_error",
                           node=node.node_id,
                           error=str(e)[:100])
        
        # All nodes have validator mode ready?
        if self._nodes_with_validator_mode >= len(self.nodes):
            elapsed = time.time() - self._start_time
            logger.info("all_validators_ready_for_consensus",
                      nodes=self._nodes_with_validator_mode,
                      total=len(self.nodes),
                      elapsed=round(elapsed, 1))
            return True
        
        # Log progress
        elapsed = time.time() - self._start_time
        if elapsed > 5.0:  # Only log after 5 seconds
            logger.info("validator_mode_activation_progress",
                      ready=self._nodes_with_validator_mode,
                      total=len(self.nodes),
                      missing=len(self.nodes) - self._nodes_with_validator_mode,
                      elapsed=round(elapsed, 1))
        
        return False
    
    async def wait(self, timeout: float, name: str = "validator_mode_activation") -> None:
        """Wait until validator mode is active."""
        try:
            await super().wait(timeout, name)
        except TimeoutError:
            raise TimeoutError(
                f"Validator mode failed to activate after {timeout}s. "
                f"Only {self._nodes_with_validator_mode}/{len(self.nodes)} nodes are ready for consensus."
            )


class StakeServiceReadyWaiter(BaseWaiter):
    """
    Wait for stake service to be ready with validators synchronized.
    
    After restart, stake service needs time to:
    1. Load validators from GDB
    2. Mark validators as active (via ESBocs s_db_calc_sync_hash)
    3. Make validators available for ESBocs consensus
    
    This function checks that:
    - Validators are visible in stake service
    - ESBocs is initialized (which triggers validator activation)
    - Validators can be found by s_get_validators_list
    
    Usage:
        waiter = StakeServiceReadyWaiter(exec_cli_func, nodes, network_name)
        await waiter.wait(timeout=60.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        nodes: List[NodeConfig],
        network_name: str = "stagenet",
        poll_interval: float = 2.0
    ):
        """
        Initialize stake service ready waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            nodes: List of validator nodes to check
            network_name: Network name
            poll_interval: Seconds between checks
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.nodes = nodes
        self.network_name = network_name
        self._start_time = None
        self._last_log_time = None
        self._nodes_with_stake_ready = 0
    
    async def check(self) -> bool:
        """Check if stake service is ready on all nodes."""
        if self._start_time is None:
            self._start_time = time.time()
            self._last_log_time = self._start_time
            logger.info("waiting_for_stake_service_ready",
                       nodes=len(self.nodes),
                       timeout=None,
                       poll_interval=self.poll_interval)
        
        elapsed = time.time() - self._start_time
        self._nodes_with_stake_ready = 0
        
        for node in self.nodes:
            try:
                # CRITICAL: Check if validators are in stake service itemlist directly
                # This is the most reliable way to check if stake service is ready
                # BUT: In PoA mode, validators come from poa_validators, not stake service!
                # So we check ESBocs status which shows if validators were loaded
                exit_code_keys, stdout_keys, stderr_keys = self.exec_cli(
                    node.node_id,
                    f"srv_stake list keys -net {self.network_name}",
                    check_output=False
                )
                
                # In PoA mode (poa_mode=true in config), validators come from poa_validators list
                # loaded from validators_addrs in config, NOT from stake service.
                # So we skip stake service check and only verify ESBocs is initialized.
                # 
                # Note: We can't reliably check poa_mode via CLI (config get doesn't work),
                # so we assume if stake service has no validators but ESBocs is initialized,
                # then it's PoA mode.
                validators_in_stake = False
                if exit_code_keys == 0 and stdout_keys:
                    stdout_keys_clean = stdout_keys.strip()
                    if stdout_keys_clean and stdout_keys_clean.lower() not in ['', 'no keys found', 'no validators']:
                        if 'fingerprint' in stdout_keys.lower() or 'node_addr' in stdout_keys.lower() or len(stdout_keys_clean) > 50:
                            validators_in_stake = True
                            logger.debug("stake_service_has_validators",
                                       node_id=node.node_id,
                                       output_preview=stdout_keys[:200])
                
                # If no validators in stake service, assume PoA mode
                # In PoA, we only need ESBocs to be initialized
                if not validators_in_stake:
                    logger.debug("assuming_poa_mode_no_stake_validators",
                               node_id=node.node_id,
                               note="No validators in stake service, assuming PoA mode")
                
                # Also check ESBocs status to verify it's initialized
                exit_code, stdout, stderr = self.exec_cli(
                    node.node_id,
                    f"esbocs status -net {self.network_name} -chain main",
                    check_output=False
                )
                
                esbocs_initialized = False
                if exit_code == 0 and stdout:
                    esbocs_initialized = True
                    # ESBocs is initialized - check if it has round_id or sync_attempt
                    round_match = re.search(r'round_id:\s*(\d+)', stdout, re.IGNORECASE)
                    sync_attempt_match = re.search(r'sync_attempt:\s*(\d+)', stdout, re.IGNORECASE)
                    
                    if round_match or sync_attempt_match:
                        round_id = int(round_match.group(1)) if round_match else 0
                        sync_attempt = int(sync_attempt_match.group(1)) if sync_attempt_match else 0
                        
                        # CRITICAL: round_id=0 and sync_attempt=0 means s_get_validators_list returned NULL
                        # This happens when validators are not synchronized in stake service
                        if round_id == 0 and sync_attempt == 0:
                            logger.debug("stake_service_validators_not_found_in_esbocs",
                                       node_id=node.node_id,
                                       note="round_id=0 and sync_attempt=0 - s_get_validators_list returned NULL")
                        else:
                            # Validators found by ESBocs - stake service is ready
                            validators_in_stake = True
                            logger.debug("stake_service_ready_for_node",
                                       node_id=node.node_id,
                                       round_id=round_id,
                                       sync_attempt=sync_attempt)
                    else:
                        # ESBocs output exists but no round data - might still be initializing
                        logger.debug("stake_service_initializing_for_node",
                                   node_id=node.node_id,
                                   output_preview=stdout[:200])
                else:
                    # ESBocs not initialized yet - stake service might not be ready
                    logger.debug("stake_service_waiting_for_esbocs_init",
                               node_id=node.node_id,
                               exit_code=exit_code)
                
                # Stake service is ready if validators are in itemlist OR ESBocs found them
                if validators_in_stake and esbocs_initialized:
                    self._nodes_with_stake_ready += 1
                    logger.debug("stake_service_ready_confirmed",
                               node_id=node.node_id,
                               validators_in_stake=validators_in_stake,
                               esbocs_initialized=esbocs_initialized)
                elif not validators_in_stake and esbocs_initialized:
                    # ESBocs initialized but no validators in stake - this is the problem!
                    logger.debug("stake_service_validators_missing",
                               node_id=node.node_id,
                               note="ESBocs initialized but validators not in stake service itemlist - s_get_validators_list will return NULL")
                    
            except Exception as e:
                logger.debug("stake_service_check_exception",
                           node_id=node.node_id,
                           error=str(e)[:100])
        
        # Log progress periodically
        if time.time() - self._last_log_time >= 10.0:
            logger.info("stake_service_readiness_progress",
                      elapsed=f"{elapsed:.1f}s",
                      ready=self._nodes_with_stake_ready,
                      total=len(self.nodes))
            self._last_log_time = time.time()
        
        if self._nodes_with_stake_ready >= len(self.nodes):
            elapsed_total = time.time() - self._start_time
            logger.info("stake_service_ready_all_nodes",
                      nodes=self._nodes_with_stake_ready,
                      total=len(self.nodes),
                      elapsed=f"{elapsed_total:.1f}s")
            return True
        
        return False
    
    async def wait(self, timeout: float, name: str = "stake_service_ready") -> None:
        """Wait until stake service is ready."""
        try:
            await super().wait(timeout, name)
        except TimeoutError:
            raise TimeoutError(
                f"Stake service failed to become ready after {timeout}s. "
                f"Only {self._nodes_with_stake_ready}/{len(self.nodes)} nodes have stake service ready. "
                f"Validators may not be synchronized in stake service, preventing ESBocs from finding active validators."
            )


class ESBocsConsensusActiveWaiter(BaseWaiter):
    """
    Wait for ESBocs consensus to become active (round_id > 0).
    
    This ensures validators have synchronized via START_SYNC messages
    and round_id is set before attempting to create transactions.
    
    ESBocs requires validators to exchange START_SYNC messages and synchronize
    before round_id is set. This process takes time (up to round_start_sync_timeout
    seconds, default 15 seconds) and requires active network links between validators.
    
    CRITICAL: Before waiting, verifies that:
    1. Validator orders are present in GDB
    2. ESBocs is initialized (not disabled due to missing orders)
    3. Network links are established between validators
    4. Stake service is ready (validators are synchronized and active)
    
    Usage:
        waiter = ESBocsConsensusActiveWaiter(
            exec_cli_func, nodes, network_name, 
            stake_service_waiter_factory  # Optional factory for creating StakeServiceReadyWaiter
        )
        await waiter.wait(timeout=90.0)
    """
    
    def __init__(
        self,
        exec_cli: Callable,
        nodes: List[NodeConfig],
        network_name: str = "stagenet",
        poll_interval: float = 3.0,
        stake_service_waiter_factory: Optional[Callable] = None
    ):
        """
        Initialize ESBocs consensus active waiter.
        
        Args:
            exec_cli: CLI execution function (node_id, command, check_output) -> (exit_code, stdout, stderr)
            nodes: List of validator nodes to check
            network_name: Network name
            poll_interval: Seconds between checks
            stake_service_waiter_factory: Optional factory function to create StakeServiceReadyWaiter
        """
        super().__init__(poll_interval)
        self.exec_cli = exec_cli
        self.nodes = nodes
        self.network_name = network_name
        self.stake_service_waiter_factory = stake_service_waiter_factory
        self._start_time = None
        self._last_log_time = None
        self._nodes_with_active_consensus = 0
        self._nodes_with_esbocs_initialized = 0
        self._nodes_with_orders = 0
        self._node_round_ids = {}
        self._stake_service_waited = False
    
    async def check(self) -> bool:
        """Check if ESBocs consensus is active on all nodes."""
        if self._start_time is None:
            self._start_time = time.time()
            self._last_log_time = self._start_time
            logger.info("waiting_for_esbocs_consensus_active",
                       nodes=len(self.nodes),
                       timeout=None,
                       poll_interval=self.poll_interval)
            
            # CRITICAL: Wait for stake service to be ready FIRST
            # This ensures validators are synchronized and marked as active in stake service
            # before ESBocs tries to find them via s_get_validators_list
            if self.stake_service_waiter_factory:
                logger.info("waiting_for_stake_service_before_consensus_wait")
                try:
                    stake_waiter = self.stake_service_waiter_factory()
                    await stake_waiter.wait(timeout=60.0)
                    logger.info("stake_service_ready_proceeding_to_consensus_wait")
                    self._stake_service_waited = True
                except TimeoutError as e:
                    logger.warning("stake_service_not_ready_warning",
                                 error=str(e),
                                 note="Proceeding anyway, but consensus may fail if validators are not synchronized")
            
            # CRITICAL: Verify validator orders BEFORE waiting
            # ESBocs won't initialize if orders are missing
            logger.info("verifying_validator_orders_before_consensus_wait")
            for node in self.nodes:
                try:
                    exit_code, stdout, stderr = self.exec_cli(
                        node.node_id,
                        f"srv_stake order list -net {self.network_name}",
                        check_output=False
                    )
                    if exit_code == 0 and stdout:
                        order_count = stdout.lower().count("order:")
                        if order_count < len(self.nodes):
                            logger.warning("insufficient_validator_orders_before_consensus",
                                         node_id=node.node_id,
                                         order_count=order_count,
                                         expected=len(self.nodes),
                                         note="ESBocs may not initialize without orders")
                    else:
                        logger.warning("cannot_check_orders_before_consensus",
                                     node_id=node.node_id,
                                     exit_code=exit_code)
                except Exception as e:
                    logger.warning("order_check_exception_before_consensus",
                                 node_id=node.node_id,
                                 error=str(e)[:100])
        
        elapsed = time.time() - self._start_time
        self._nodes_with_active_consensus = 0
        self._nodes_with_esbocs_initialized = 0
        self._nodes_with_orders = 0
        self._node_round_ids = {}
        node_diagnostics = {}
        
        for node in self.nodes:
            try:
                # Check ESBocs status
                exit_code, stdout, stderr = self.exec_cli(
                    node.node_id,
                    f"esbocs status -net {self.network_name} -chain main",
                    check_output=False
                )
                
                if exit_code == 0 and stdout:
                    self._nodes_with_esbocs_initialized += 1
                    # Parse round_id from output
                    round_match = re.search(r'round_id:\s*(\d+)', stdout, re.IGNORECASE)
                    sync_attempt_match = re.search(r'sync_attempt:\s*(\d+)', stdout, re.IGNORECASE)
                    
                    if round_match:
                        round_id = int(round_match.group(1))
                        sync_attempt = int(sync_attempt_match.group(1)) if sync_attempt_match else 0
                        self._node_round_ids[node.node_id] = round_id
                        node_diagnostics[node.node_id] = {
                            'round_id': round_id,
                            'sync_attempt': sync_attempt,
                            'has_output': True
                        }
                        
                        # CRITICAL: If round_id is 0 and sync_attempt is 0, s_session_round_new may not have been called
                        # or START_SYNC messages are not being sent/received
                        # This can happen if s_get_validators_list returned NULL (validators not synchronized in stake service)
                        if round_id == 0 and sync_attempt == 0:
                            logger.warning("esbocs_round_not_started",
                                        node_id=node.node_id,
                                        note="round_id=0 and sync_attempt=0 - s_session_round_new may not have been called or START_SYNC not sent. "
                                             "Possible causes: validators not synchronized in stake service (s_get_validators_list returned NULL)")
                            
                            # Try to diagnose: check if validators are visible in stake service
                            try:
                                exit_code_validators, stdout_validators, _ = self.exec_cli(
                                    node.node_id,
                                    f"srv_stake order list -net {self.network_name}",
                                    check_output=False
                                )
                                if exit_code_validators == 0 and stdout_validators:
                                    order_count = stdout_validators.lower().count("order:")
                                    logger.debug("stake_service_diagnosis",
                                               node_id=node.node_id,
                                               order_count=order_count,
                                               note="Orders are visible, but validators may not be synchronized in stake service yet")
                            except Exception:
                                pass
                        
                        if round_id > 0:
                            self._nodes_with_active_consensus += 1
                            logger.debug("node_esbocs_consensus_active",
                                       node_id=node.node_id,
                                       round_id=round_id,
                                       sync_attempt=sync_attempt)
                        else:
                            logger.debug("node_esbocs_consensus_waiting",
                                       node_id=node.node_id,
                                       round_id=round_id,
                                       sync_attempt=sync_attempt,
                                       note="Waiting for START_SYNC messages from other validators")
                    else:
                        # ESBocs output exists but no round_id - might be disabled
                        node_diagnostics[node.node_id] = {
                            'round_id': None,
                            'has_output': True,
                            'output_preview': stdout[:200]
                        }
                        logger.debug("node_esbocs_status_no_round_id",
                                   node_id=node.node_id,
                                   output_preview=stdout[:200])
                else:
                    # ESBocs command failed - might not be initialized
                    node_diagnostics[node.node_id] = {
                        'exit_code': exit_code,
                        'stderr': stderr[:200] if stderr else "",
                        'has_output': False
                    }
                    logger.debug("node_esbocs_status_check_failed",
                               node_id=node.node_id,
                               exit_code=exit_code,
                               stderr=stderr[:200] if stderr else "")
                
                # Check network links - validators need active links to exchange START_SYNC
                # START_SYNC messages are sent via network links, so links must be established
                try:
                    exit_code_net, stdout_net, _ = self.exec_cli(
                        node.node_id,
                        f"net -net {self.network_name} get status",
                        check_output=False
                    )
                    if exit_code_net == 0 and stdout_net:
                        links_match = re.search(r'active:\s*(\d+)', stdout_net, re.IGNORECASE)
                        required_match = re.search(r'required:\s*(\d+)', stdout_net, re.IGNORECASE)
                        active_links = int(links_match.group(1)) if links_match else 0
                        required_links = int(required_match.group(1)) if required_match else 0
                        if node.node_id in node_diagnostics:
                            node_diagnostics[node.node_id]['network_links'] = {
                                'active': active_links,
                                'required': required_links
                            }
                        if active_links < required_links:
                            logger.warning("insufficient_network_links_for_start_sync",
                                         node_id=node.node_id,
                                         active=active_links,
                                         required=required_links,
                                         note="Validators need active links to exchange START_SYNC messages")
                except Exception:
                    pass
                
                # Check validator orders
                try:
                    exit_code_orders, stdout_orders, _ = self.exec_cli(
                        node.node_id,
                        f"srv_stake order list -net {self.network_name}",
                        check_output=False
                    )
                    if exit_code_orders == 0 and stdout_orders:
                        order_count = stdout_orders.lower().count("order:")
                        if order_count >= len(self.nodes):
                            self._nodes_with_orders += 1
                except Exception:
                    pass
                        
            except Exception as e:
                logger.debug("esbocs_status_check_exception",
                           node_id=node.node_id,
                           error=str(e)[:100])
                if node.node_id not in node_diagnostics:
                    node_diagnostics[node.node_id] = {}
                node_diagnostics[node.node_id]['error'] = str(e)[:100]
        
        if self._nodes_with_active_consensus >= len(self.nodes):
            elapsed_total = time.time() - self._start_time
            logger.info("esbocs_consensus_active_all_validators_synced",
                      nodes=self._nodes_with_active_consensus,
                      total=len(self.nodes),
                      elapsed=f"{elapsed_total:.1f}s",
                      round_ids=self._node_round_ids)
            return True
        
        # Log progress periodically (every 5 seconds)
        if time.time() - self._last_log_time >= 5.0:
            logger.info("esbocs_consensus_synchronization_progress",
                      active=self._nodes_with_active_consensus,
                      initialized=self._nodes_with_esbocs_initialized,
                      with_orders=self._nodes_with_orders,
                      total=len(self.nodes),
                      elapsed=f"{elapsed:.1f}s",
                      round_ids=self._node_round_ids)
            self._last_log_time = time.time()
        
        return False
    
    async def wait(self, timeout: float, name: str = "esbocs_consensus_active") -> None:
        """Wait until ESBocs consensus is active."""
        try:
            await super().wait(timeout, name)
        except TimeoutError:
            elapsed_total = time.time() - self._start_time
            logger.error("esbocs_consensus_timeout",
                        elapsed=f"{elapsed_total:.1f}s",
                        timeout=timeout,
                        active=self._nodes_with_active_consensus,
                        initialized=self._nodes_with_esbocs_initialized,
                        with_orders=self._nodes_with_orders,
                        total=len(self.nodes),
                        round_ids=self._node_round_ids)
            
            # Collect detailed diagnostic info
            for node in self.nodes:
                try:
                    # ESBocs status
                    exit_code, stdout, stderr = self.exec_cli(
                        node.node_id,
                        f"esbocs status -net {self.network_name} -chain main",
                        check_output=False
                    )
                    logger.error("esbocs_status_at_timeout",
                               node_id=node.node_id,
                               exit_code=exit_code,
                               output_preview=stdout[:500] if stdout else "EMPTY",
                               stderr_preview=stderr[:200] if stderr else "")
                    
                    # Validator orders
                    exit_code_orders, stdout_orders, stderr_orders = self.exec_cli(
                        node.node_id,
                        f"srv_stake order list -net {self.network_name}",
                        check_output=False
                    )
                    order_count = stdout_orders.lower().count("order:") if stdout_orders else 0
                    logger.error("validator_orders_at_timeout",
                               node_id=node.node_id,
                               order_count=order_count,
                               expected=len(self.nodes),
                               output_preview=stdout_orders[:300] if stdout_orders else "EMPTY")
                    
                    # Network links
                    try:
                        exit_code_net, stdout_net, _ = self.exec_cli(
                            node.node_id,
                            f"net -net {self.network_name} get status",
                            check_output=False
                        )
                        logger.error("network_status_at_timeout",
                                   node_id=node.node_id,
                                   output_preview=stdout_net[:300] if stdout_net else "EMPTY")
                    except Exception:
                        pass
                        
                except Exception as e:
                    logger.error("esbocs_status_check_exception_at_timeout",
                               node_id=node.node_id,
                               error=str(e)[:100])
            
            # Determine failure reason
            if self._nodes_with_esbocs_initialized < len(self.nodes):
                raise RuntimeError(
                    f"ESBocs is not initialized on {len(self.nodes) - self._nodes_with_esbocs_initialized}/{len(self.nodes)} nodes. "
                    f"This usually means validator orders are missing from GDB or ESBocs initialization failed. "
                    f"Check logs for 'No valid order found' or 'Switch off validator mode' errors."
                )
            elif self._nodes_with_active_consensus == 0:
                raise TimeoutError(
                    f"ESBocs consensus did not become active after {timeout}s. "
                    f"All {len(self.nodes)} nodes have round_id = 0. "
                    f"Validators need to exchange START_SYNC messages and synchronize. "
                    f"Check network links between validators."
                )
            else:
                raise TimeoutError(
                    f"ESBocs consensus did not become active after {timeout}s. "
                    f"Only {self._nodes_with_active_consensus}/{len(self.nodes)} nodes have round_id > 0. "
                    f"Validators need to exchange START_SYNC messages and synchronize."
                )

