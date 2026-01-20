"""E2E tests for monitoring and observability."""

import pytest
import time


class TestLoggingAndMonitoring:
    """Test logging and monitoring capabilities."""
    
    def test_logs_are_available(self, running_network):
        """Test that logs can be retrieved."""
        containers = running_network.get_running_containers()
        
        if not containers:
            pytest.skip("No containers running")
        
        # Get logs from first container
        logs = running_network.get_logs(containers[0], tail=50)
        
        # Should get some logs
        assert logs is not None
        assert len(logs) > 0, "No logs retrieved"
    
    def test_network_status_queryable(self, running_network):
        """Test network status can be queried."""
        # Check multiple times
        for _ in range(3):
            is_ready = running_network.is_network_ready()
            assert is_ready, "Network should remain ready"
            time.sleep(2)
    
    def test_containers_list_consistent(self, running_network):
        """Test container list remains consistent."""
        containers1 = running_network.get_running_containers()
        time.sleep(5)
        containers2 = running_network.get_running_containers()
        
        assert len(containers1) == len(containers2), \
            "Container count changed unexpectedly"


class TestPerformanceBasics:
    """Basic performance tests."""
    
    def test_startup_time_reasonable(self, clean_environment, lifecycle):
        """Test network starts in reasonable time."""
        start_time = time.time()
        
        lifecycle.run(detach=True, wait_ready=True, timeout=300)
        
        elapsed = time.time() - start_time
        
        lifecycle.stop_network()
        
        # Should start in under 3 minutes
        assert elapsed < 180, f"Startup took {elapsed}s, expected < 180s"
    
    def test_shutdown_time_reasonable(self, running_network):
        """Test network stops in reasonable time."""
        start_time = time.time()
        
        success = running_network.stop_network(timeout=60)
        
        elapsed = time.time() - start_time
        
        assert success, "Stop failed"
        assert elapsed < 60, f"Shutdown took {elapsed}s, expected < 60s"
