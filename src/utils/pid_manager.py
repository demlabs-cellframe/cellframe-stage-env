"""PID file manager to prevent multiple instances of stage-env."""

import os
import signal
from pathlib import Path
from typing import Optional

from .logger import get_logger

logger = get_logger(__name__)


class PIDManager:
    """Manage PID file for stage-env to prevent multiple instances."""
    
    def __init__(self, base_path: Path):
        """
        Initialize PID manager.
        
        Args:
            base_path: Base directory for stage-env
        """
        self.base_path = base_path
        self.pid_file = base_path / ".stage-env.pid"
        self.pid = os.getpid()
    
    def check_and_create(self) -> bool:
        """
        Check if another instance is running and create PID file.
        
        Returns:
            True if PID file created successfully, False if another instance is running
        """
        if self.pid_file.exists():
            # Read existing PID
            try:
                with open(self.pid_file, 'r') as f:
                    old_pid = int(f.read().strip())
                
                # Check if process is still running
                if self._is_process_running(old_pid):
                    logger.error(
                        "another_instance_running",
                        pid=old_pid,
                        pid_file=str(self.pid_file)
                    )
                    return False
                else:
                    logger.warning(
                        "stale_pid_file_found",
                        old_pid=old_pid,
                        action="removing"
                    )
                    self.pid_file.unlink()
            except (ValueError, OSError) as e:
                logger.warning(
                    "invalid_pid_file",
                    error=str(e),
                    action="removing"
                )
                try:
                    self.pid_file.unlink()
                except OSError:
                    pass
        
        # Create new PID file
        try:
            with open(self.pid_file, 'w') as f:
                f.write(str(self.pid))
            logger.debug("pid_file_created", pid=self.pid, path=str(self.pid_file))
            return True
        except OSError as e:
            logger.error("pid_file_creation_failed", error=str(e))
            return False
    
    def get_running_pid(self) -> Optional[int]:
        """
        Get PID from file if process is running.
        
        Returns:
            PID if file exists and process is running, None otherwise
        """
        if not self.pid_file.exists():
            return None
        
        try:
            with open(self.pid_file, 'r') as f:
                file_pid = int(f.read().strip())
            
            if self._is_process_running(file_pid):
                return file_pid
            else:
                # Stale PID file
                return None
        except (ValueError, OSError) as e:
            logger.warning("failed_to_read_pid_file", error=str(e))
            return None
    
    def remove(self) -> None:
        """Remove PID file."""
        if self.pid_file.exists():
            try:
                # Verify it's our PID before removing
                with open(self.pid_file, 'r') as f:
                    file_pid = int(f.read().strip())
                
                if file_pid == self.pid:
                    self.pid_file.unlink()
                    logger.debug("pid_file_removed", pid=self.pid)
                else:
                    logger.warning(
                        "pid_file_mismatch",
                        our_pid=self.pid,
                        file_pid=file_pid,
                        action="not_removing"
                    )
            except (ValueError, OSError) as e:
                logger.warning("pid_file_removal_failed", error=str(e))
    
    @staticmethod
    def _is_process_running(pid: int) -> bool:
        """
        Check if process with given PID is running.
        
        Args:
            pid: Process ID to check
            
        Returns:
            True if process is running, False otherwise
        """
        try:
            # Send signal 0 - doesn't actually send signal, just checks if process exists
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    
    def __enter__(self):
        """Context manager entry."""
        if not self.check_and_create():
            raise RuntimeError(
                f"Another instance of stage-env is already running. "
                f"PID file: {self.pid_file}\n"
                f"If you're sure no other instance is running, remove the PID file manually: "
                f"rm {self.pid_file}"
            )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.remove()
        return False

