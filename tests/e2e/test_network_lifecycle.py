"""E2E tests for basic network lifecycle."""

import pytest
import time


class TestNetworkStartup:
    """Test network startup via scripts/run.sh."""
    
    def test_clean_script_runs_successfully(self, lifecycle):
        """Test clean.sh runs without errors."""
        returncode, stdout, stderr = lifecycle.clean()
        assert returncode == 0, f"clean.sh failed: {stderr}"
    
    def test_run_script_starts_network(self, clean_environment, lifecycle):
        """Test run.sh starts network successfully."""
        returncode, stdout, stderr = lifecycle.run(
            detach=True,
            wait_ready=False,
            timeout=180
        )
        
        assert returncode == 0, f"run.sh failed: {stderr}"
        
        # Cleanup
        lifecycle.stop_network()
    
    def test_network_becomes_ready(self, clean_environment, lifecycle):
        """Test network becomes ready after startup."""
        lifecycle.run(detach=True, wait_ready=False, timeout=180)
        
        # Wait for network
        is_ready = lifecycle.wait_for_network_ready(timeout=90)
        
        # Cleanup
        lifecycle.stop_network()
        
        assert is_ready, "Network did not become ready"
    
    def test_containers_are_running(self, running_network):
        """Test that containers are running."""
        containers = running_network.get_running_containers()
        
        assert len(containers) > 0, "No containers are running"
        assert any("cellframe-stage" in c for c in containers), \
            f"No cellframe-stage containers found: {containers}"


class TestNetworkShutdown:
    """Test network shutdown."""
    
    def test_network_stops_gracefully(self, running_network):
        """Test network can be stopped gracefully."""
        success = running_network.stop_network(timeout=60)
        assert success, "Failed to stop network"
        
        # Verify no containers running
        time.sleep(5)
        containers = running_network.get_running_containers()
        assert len(containers) == 0, f"Containers still running: {containers}"
    
    def test_clean_after_run(self, clean_environment, lifecycle):
        """Test clean.sh works after network run."""
        # Start and stop network
        lifecycle.run(detach=True, wait_ready=False, timeout=180)
        time.sleep(10)
        lifecycle.stop_network()
        
        # Clean should work
        returncode, stdout, stderr = lifecycle.clean()
        assert returncode == 0, f"clean.sh failed after run: {stderr}"


class TestNetworkRestart:
    """Test network restart scenarios."""
    
    def test_network_can_restart(self, clean_environment, lifecycle):
        """Test network can be restarted."""
        # First run
        lifecycle.run(detach=True, wait_ready=True, timeout=180)
        containers_first = lifecycle.get_running_containers()
        assert len(containers_first) > 0
        
        # Stop
        lifecycle.stop_network()
        time.sleep(5)
        
        # Second run
        lifecycle.run(detach=True, wait_ready=True, timeout=180)
        containers_second = lifecycle.get_running_containers()
        assert len(containers_second) > 0
        
        # Cleanup
        lifecycle.stop_network()
