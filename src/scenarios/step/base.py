"""
Base step executor class.
"""

from typing import Optional
from pathlib import Path

from ...docker.container import DockerContainerManager


class StepExecutor:
    """Base class for step executors."""
    
    def __init__(
        self,
        container_manager: DockerContainerManager,
        log_file: Optional[Path] = None,
        debug: bool = False
    ):
        """
        Initialize step executor.
        
        Args:
            container_manager: Docker container manager instance
            log_file: Optional log file for detailed logging
            debug: Enable debug logging
        """
        self.container_manager = container_manager
        self.log_file = log_file
        self.debug = debug
    
    def _log_to_file(self, message: str):
        """Write message to log file if enabled."""
        if self.log_file:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(message + '\n')

