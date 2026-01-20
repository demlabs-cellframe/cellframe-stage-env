"""E2E test helpers for stage-env lifecycle management."""

import subprocess
import time
from pathlib import Path
from typing import Optional, List, Tuple
import logging

logger = logging.getLogger(__name__)


class StageEnvLifecycle:
    """Helper class for managing stage-env lifecycle via scripts."""
    
    def __init__(self, stage_env_root: Path):
        self.root = stage_env_root
        self.clean_script = self.root / "scripts" / "clean.sh"
        self.run_script = self.root / "scripts" / "run.sh"
        
        if not self.clean_script.exists():
            raise FileNotFoundError(f"clean.sh not found at {self.clean_script}")
        if not self.run_script.exists():
            raise FileNotFoundError(f"run.sh not found at {self.run_script}")
    
    def clean(self, verbose: bool = False) -> Tuple[int, str, str]:
        """Run scripts/clean.sh to clean up environment."""
        logger.info("Running clean.sh...")
        cmd = [str(self.clean_script)]
        if verbose:
            cmd.append("-v")
        
        result = subprocess.run(
            cmd,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        logger.info(f"clean.sh completed with exit code {result.returncode}")
        return result.returncode, result.stdout, result.stderr
    
    def run(
        self,
        config: Optional[str] = None,
        scenario: Optional[str] = None,
        detach: bool = True,
        wait_ready: bool = True,
        timeout: int = 300
    ) -> Tuple[int, str, str]:
        """Run scripts/run.sh to start stage-env network."""
        logger.info("Running run.sh...")
        cmd = [str(self.run_script)]
        
        if config:
            cmd.extend(["-c", config])
        if scenario:
            cmd.extend(["-s", scenario])
        if detach:
            cmd.append("-d")
        
        result = subprocess.run(
            cmd,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        logger.info(f"run.sh completed with exit code {result.returncode}")
        
        if result.returncode == 0 and wait_ready:
            self.wait_for_network_ready(timeout=60)
        
        return result.returncode, result.stdout, result.stderr
    
    def wait_for_network_ready(self, timeout: int = 60, check_interval: int = 2) -> bool:
        """Wait for network to be ready."""
        logger.info(f"Waiting for network to be ready (timeout={timeout}s)...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self.is_network_ready():
                logger.info("Network is ready!")
                return True
            time.sleep(check_interval)
        
        logger.warning(f"Network not ready after {timeout}s")
        return False
    
    def is_network_ready(self) -> bool:
        """Check if network is ready."""
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=cellframe-stage", "--format", "{{.Status}}"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                return False
            
            statuses = result.stdout.strip().split('\n')
            running_count = sum(1 for status in statuses if status.startswith("Up"))
            
            return running_count > 0
            
        except Exception as e:
            logger.error(f"Error checking network status: {e}")
            return False
    
    def get_running_containers(self) -> List[str]:
        """Get list of running stage-env containers."""
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=cellframe-stage", "--format", "{{.Names}}"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                return []
            
            return [name for name in result.stdout.strip().split('\n') if name]
            
        except Exception as e:
            logger.error(f"Error getting container list: {e}")
            return []
    
    def stop_network(self, timeout: int = 30) -> bool:
        """Stop the network gracefully."""
        logger.info("Stopping network...")
        try:
            result = subprocess.run(
                ["docker", "compose", "down"],
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return result.returncode == 0
            
        except Exception as e:
            logger.error(f"Error stopping network: {e}")
            return False
