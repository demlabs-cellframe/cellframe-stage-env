"""
Base monitor class for periodic state polling with configurable logging.

Provides common functionality for all monitoring services:
- Periodic polling with timeout
- Structured logging at intervals
- Progress tracking
- Configuration from stage-env.cfg
"""

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..utils.logger import get_logger


logger = get_logger(__name__)


@dataclass
class MonitorConfig:
    """
    Configuration for monitoring behavior.
    
    Note: Monitors always WORK when called - log_enabled only controls LOGGING.
    """
    log_enabled: bool = True    # enable periodic progress logging
    poll_interval: float = 2.0  # seconds between condition checks
    log_interval: float = 5.0   # seconds between progress logs (if log_enabled)
    timeout: float = 60.0       # total timeout
    verbose: bool = True        # detailed per-node logging


class BaseMonitor(ABC):
    """
    Base class for all monitoring services.
    
    Stateless monitor - creates fresh state for each wait_until_ready() call.
    Monitor is SILENT when not actively waiting for a condition.
    
    Provides:
    - Periodic polling with configurable intervals
    - Progress logging at regular intervals (ONLY during active wait)
    - Timeout handling
    - Structured state tracking
    
    Key Design:
    - Monitors don't run in background - they wait synchronously
    - Each wait_until_ready() call is independent
    - No persistent state between calls
    - Logging only happens during active waiting
    
    Usage:
        class MyMonitor(BaseMonitor):
            async def _check_condition(self) -> tuple[bool, dict]:
                # Check if condition is met
                return (is_ready, state_info)
            
            def _log_progress(self, elapsed: float, state: dict):
                # Log current progress
                logger.info("my_progress", elapsed=elapsed, **state)
        
        monitor = MyMonitor(config)
        result = await monitor.wait_until_ready(name="my_check")
        # Monitor is now SILENT until next wait_until_ready() call
    """
    
    def __init__(self, config: MonitorConfig):
        """
        Initialize base monitor.
        
        Args:
            config: Monitor configuration
        """
        self.config = config
    
    @abstractmethod
    async def _check_condition(self) -> tuple[bool, Dict[str, Any]]:
        """
        Check if monitored condition is met.
        
        Must be implemented by subclasses.
        
        Returns:
            Tuple of (condition_met, state_info)
            - condition_met: True if waiting should stop
            - state_info: Dict with current state for logging
        """
        pass
    
    @abstractmethod
    def _log_progress(self, elapsed: float, state: Dict[str, Any]) -> None:
        """
        Log monitoring progress.
        
        Must be implemented by subclasses.
        
        Args:
            elapsed: Time elapsed since start (seconds)
            state: Current state information
        """
        pass
    
    def _should_log(self, last_log_time: Optional[float]) -> bool:
        """
        Check if it's time to log progress.
        
        Args:
            last_log_time: Timestamp of last log, or None for first log
        
        Returns:
            True if enough time has passed since last log
        """
        # Logging disabled entirely
        if not self.config.log_enabled:
            return False
        
        # First log always shown (if logging enabled)
        if last_log_time is None:
            return True
        
        # Check if enough time passed since last log
        return (time.time() - last_log_time) >= self.config.log_interval
    
    async def wait_until_ready(
        self,
        name: str,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Wait until monitored condition is met.
        
        Args:
            name: Human-readable name for this wait operation
            timeout: Override default timeout (seconds)
            
        Returns:
            Final state information
            
        Raises:
            TimeoutError: If condition not met within timeout
        """
        # Monitor always works - just might not log progress
        
        timeout = timeout or self.config.timeout
        start_time = time.time()
        last_log_time = None
        iteration = 0
        
        if self.config.log_enabled:
            logger.info(f"{name}_started",
                       timeout=timeout,
                       poll_interval=self.config.poll_interval,
                       log_interval=self.config.log_interval)
        
        while True:
            iteration += 1
            elapsed = time.time() - start_time
            
            # Check timeout
            if elapsed >= timeout:
                logger.error(f"{name}_timeout",
                           elapsed=f"{elapsed:.1f}s",
                           iterations=iteration)
                raise TimeoutError(
                    f"{name} timeout after {elapsed:.1f}s "
                    f"({iteration} iterations)"
                )
            
            # Check condition
            try:
                condition_met, state = await self._check_condition()
                
                # Log progress if needed
                if self._should_log(last_log_time):
                    self._log_progress(elapsed, state)
                    last_log_time = time.time()
                
                # Check if done
                if condition_met:
                    if self.config.log_enabled:
                        logger.info(f"{name}_completed",
                                   elapsed=f"{elapsed:.1f}s",
                                   iterations=iteration,
                                   final_state=state)
                    return state
                
            except Exception as e:
                logger.error(f"{name}_check_failed",
                           elapsed=f"{elapsed:.1f}s",
                           error=str(e))
                # Continue monitoring despite errors
            
            # Wait before next check
            await asyncio.sleep(self.config.poll_interval)


class BaseWaiter(ABC):
    """
    Base class for waiters (used in scenario interpreter and genesis).

    Similar to BaseMonitor but simpler interface for one-off waits.
    Compatible with WaitStep in scenario language.

    Subclasses may override ``notify_matches`` to enable event-driven waiting
    via the Cellframe Node notify server.  When ``enable_notify`` is called
    the waiter uses pure notify listening (no polling).  If the notify
    connection cannot be established, the waiter falls back to polling.

    Backward compatibility with SDK <=5.7 (limited notifiers): if the
    notify server is unreachable or doesn't exist, ``connect()`` fails
    immediately and the waiter falls back to polling with no timeout
    penalty.  If the server is reachable but the expected event class
    is never emitted (e.g. GDBEvent on 5.7), the waiter times out
    normally — callers should set appropriate timeouts.
    """

    def __init__(self, poll_interval: float = 2.0):
        self.poll_interval = poll_interval
        self._notify_host: Optional[str] = None
        self._notify_classes: set = set()
        self._notify_hint_mode: bool = False

    def enable_notify(self, host: str, notify_class: str, *,
                      hint_only: bool = False) -> None:
        """Activate notify-based waiting with polling as fallback.

        May be called multiple times to listen for several event classes
        (e.g. both ``MempoolEvent`` and ``LedgerTxEvent``).

        Args:
            host: Container IP for the notify server.
            notify_class: Event class to listen for (e.g. ``"GDBEvent"``).
            hint_only: When True, a notify match triggers an immediate
                ``check()`` instead of completing the waiter directly.
                Useful for multi-node waiters where a single notification
                doesn't prove the condition is met on ALL nodes.
        """
        self._notify_host = host
        self._notify_classes.add(notify_class)
        if hint_only:
            self._notify_hint_mode = True

    def notify_matches(self, msg: Dict[str, Any]) -> bool:
        """Return True when *msg* satisfies this waiter's condition.

        Override in subclasses that support notify.  The default returns
        ``False`` so that waiters without an override never match and fall
        through to polling.
        """
        return False

    @abstractmethod
    async def check(self) -> bool:
        """Check if condition is met (polling mode)."""
        pass

    async def wait(self, timeout: float, name: str = "condition") -> None:
        start = time.time()

        if self._notify_host and self._notify_classes:
            try:
                await self._wait_via_notify(timeout, name)
                return
            except TimeoutError:
                raise
            except Exception as exc:
                logger.info(f"{name}: notify unavailable ({exc}), "
                            "falling back to polling")

        remaining = timeout - (time.time() - start)
        if remaining <= 0:
            raise TimeoutError(f"{name} timeout after {timeout:.1f}s")
        await self._wait_polling(remaining, name)

    async def _wait_polling(self, timeout: float, name: str) -> None:
        """Pure polling loop."""
        start_time = time.time()
        while True:
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                raise TimeoutError(f"{name} timeout after {elapsed:.1f}s")
            if await self.check():
                logger.debug(f"{name}_ready", elapsed=f"{elapsed:.1f}s")
                return
            await asyncio.sleep(self.poll_interval)

    async def _wait_via_notify(self, timeout: float, name: str) -> None:
        """Pure notify listening.  No polling runs alongside.

        For hint_only mode an initial ``check()`` is performed before
        listening — this covers the case where the condition was already
        met before we connected to the notify server.
        """
        from .notify_client import NotifyClient

        client = NotifyClient()
        await client.connect(self._notify_host, timeout=min(timeout, 5.0))

        classes_str = ",".join(sorted(self._notify_classes))
        logger.debug(f"{name}: listening via notify (classes={classes_str})")

        try:
            if self._notify_hint_mode and await self.check():
                logger.debug(f"{name}: condition already met before notify")
                return

            async def _scan():
                async for msg in client.messages():
                    if msg.get("class") not in self._notify_classes:
                        continue
                    if not self.notify_matches(msg):
                        continue
                    if self._notify_hint_mode:
                        if await self.check():
                            logger.info(f"{name}: notify hint -> check() passed",
                                        cls=msg.get("class"))
                            return
                    else:
                        logger.info(f"{name}: notify matched",
                                    cls=msg.get("class"))
                        return
                raise ConnectionError("notify stream closed before match")

            await asyncio.wait_for(_scan(), timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"{name} timeout after {timeout:.1f}s")
        finally:
            await client.close()

