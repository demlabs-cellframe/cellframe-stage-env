"""E2E tests for network resilience."""

import pytest
import time


class TestNetworkResilience:
    """Test network resilience and stability."""
    
    def test_network_stays_up(self, running_network):
        """Test network remains stable over time."""
        # Check network stays up for 30 seconds
        for i in range(6):
            is_ready = running_network.is_network_ready()
            assert is_ready, f"Network went down at iteration {i}"
            time.sleep(5)
    
    def test_container_count_stable(self, running_network):
        """Test container count remains stable."""
        initial_count = len(running_network.get_running_containers())
        
        time.sleep(20)
        
        final_count = len(running_network.get_running_containers())
        
        assert initial_count == final_count, \
            f"Container count changed from {initial_count} to {final_count}"
    
    def test_repeated_status_checks(self, running_network):
        """Test repeated status checks don't cause issues."""
        # Query status many times rapidly
        for _ in range(20):
            running_network.is_network_ready()
            running_network.get_running_containers()
        
        # Network should still be healthy
        assert running_network.is_network_ready()


class TestCleanupRobustness:
    """Test cleanup robustness."""
    
    def test_multiple_clean_calls(self, lifecycle):
        """Test multiple clean calls are safe."""
        for i in range(3):
            returncode, stdout, stderr = lifecycle.clean()
            # Clean should always succeed or be idempotent
            assert returncode in [0, 1], f"Clean {i} failed unexpectedly"
    
    def test_clean_after_partial_start(self, clean_environment, lifecycle):
        """Test clean works after partial/interrupted start."""
        # Start but don't wait
        lifecycle.run(detach=True, wait_ready=False, timeout=180)
        time.sleep(2)  # Let it partially start
        
        # Immediately clean
        returncode, stdout, stderr = lifecycle.clean()
        
        # Should handle this case
        assert returncode in [0, 1], f"Clean after partial start failed: {stderr}"
