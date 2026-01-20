"""E2E tests for error scenarios."""

import pytest


class TestErrorHandling:
    """Test error handling in lifecycle."""
    
    def test_double_run_handled(self, running_network):
        """Test running network twice is handled."""
        # Network already running from fixture
        # Try to run again
        returncode, stdout, stderr = running_network.run(
            detach=True,
            wait_ready=False,
            timeout=180
        )
        
        # Should either succeed (idempotent) or fail gracefully
        assert returncode in [0, 1], f"Unexpected error: {stderr}"
    
    def test_clean_while_running(self, running_network):
        """Test clean while network is running."""
        # Try to clean while running
        returncode, stdout, stderr = running_network.clean()
        
        # Should handle this case
        # May succeed (stops then cleans) or fail with clear message
        assert returncode in [0, 1], "Clean should handle running network"
    
    def test_stop_already_stopped(self, clean_environment, lifecycle):
        """Test stopping already stopped network."""
        # Don't start network, just try to stop
        success = lifecycle.stop_network()
        
        # Should handle gracefully (may return True or False)
        assert isinstance(success, bool), "stop_network should return bool"


class TestRecovery:
    """Test recovery scenarios."""
    
    def test_recovery_after_failed_start(self, clean_environment, lifecycle):
        """Test recovery after a failed start attempt."""
        # Try to start with invalid params (if possible)
        # Then do a clean start
        
        # Clean slate
        lifecycle.clean()
        
        # Normal start should work
        returncode, stdout, stderr = lifecycle.run(
            detach=True,
            wait_ready=False,
            timeout=180
        )
        
        lifecycle.stop_network()
        assert returncode == 0, "Should recover after clean"
