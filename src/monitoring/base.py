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
    """Configuration for monitoring behavior."""
    enabled: bool = True
    poll_interval: float = 2.0  # seconds between checks
    log_interval: float = 5.0   # seconds between progress logs
    timeout: float = 60.0       # total timeout
    verbose: bool = True        # detailed logging


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
        if not self.config.verbose:
            return False
        
        if last_log_time is None:
            return True
        
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
        if not self.config.enabled:
            logger.warning("monitoring_disabled", name=name)
            return {}
        
        timeout = timeout or self.config.timeout
        start_time = time.time()
        last_log_time = None
        iteration = 0
        
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
    """
    
    def __init__(self, poll_interval: float = 2.0):
        """
        Initialize waiter.
        
        Args:
            poll_interval: Seconds between condition checks
        """
        self.poll_interval = poll_interval
    
    @abstractmethod
    async def check(self) -> bool:
        """
        Check if condition is met.
        
        Returns:
            True if waiting should stop
        """
        pass
    
    async def wait(self, timeout: float, name: str = "condition") -> None:
        """
        Wait until condition is met.
        
        Args:
            timeout: Maximum wait time (seconds)
            name: Name for logging
            
        Raises:
            TimeoutError: If condition not met within timeout
        """
        start_time = time.time()
        
        while True:
            elapsed = time.time() - start_time
            
            if elapsed >= timeout:
                raise TimeoutError(f"{name} timeout after {elapsed:.1f}s")
            
            if await self.check():
                logger.debug(f"{name}_ready", elapsed=f"{elapsed:.1f}s")
                return
            
            await asyncio.sleep(self.poll_interval)

