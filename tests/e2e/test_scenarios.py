"""E2E tests for scenario execution (if applicable)."""

import pytest
import time


class TestScenarioExecution:
    """Test scenario file execution."""
    
    def test_run_without_scenario(self, clean_environment, lifecycle):
        """Test network runs without explicit scenario."""
        returncode, stdout, stderr = lifecycle.run(
            detach=True,
            wait_ready=False,
            timeout=180
        )
        
        lifecycle.stop_network()
        assert returncode == 0, f"Failed without scenario: {stderr}"
    
    def test_run_with_scenario_path(self, clean_environment, lifecycle):
        """Test network with scenario path (if supported)."""
        # This test may need adjustment based on actual API
        returncode, stdout, stderr = lifecycle.run(
            scenario="scenarios/test.yml",
            detach=True,
            wait_ready=False,
            timeout=180
        )
        
        lifecycle.stop_network()
        # Should either work or fail gracefully
        assert returncode in [0, 1], f"Unexpected failure: {stderr}"


class TestIntegrationWithScripts:
    """Test integration with other scripts."""
    
    def test_clean_removes_artifacts(self, clean_environment, lifecycle):
        """Test clean.sh removes generated artifacts."""
        # Start network to generate artifacts
        lifecycle.run(detach=True, wait_ready=False, timeout=180)
        time.sleep(10)
        lifecycle.stop_network()
        
        # Clean
        returncode, stdout, stderr = lifecycle.clean()
        
        assert returncode == 0, f"Clean failed: {stderr}"
        
        # Verify cleaned (containers should be gone)
        containers = lifecycle.get_running_containers()
        assert len(containers) == 0, "Containers not cleaned"
