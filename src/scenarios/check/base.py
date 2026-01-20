"""
Base check executor class.
"""

from typing import Optional
from pathlib import Path

from ...docker_ctl.container import DockerContainerManager


class CheckExecutor:
    """Base class for check executors."""
    
    def __init__(
        self,
        container_manager: DockerContainerManager,
        log_file: Optional[Path] = None,
        debug: bool = False
    ):
        """
        Initialize check executor.
        
        Args:
            container_manager: Docker container manager instance
            log_file: Optional log file for detailed logging
            debug: Enable debug logging
        """
        self.container_manager = container_manager
        self.log_file = log_file
        self.debug = debug

