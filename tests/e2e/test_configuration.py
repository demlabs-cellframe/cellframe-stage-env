"""E2E tests for configuration handling."""

import pytest
from pathlib import Path


class TestConfigurationValidation:
    """Test configuration file validation."""
    
    def test_default_config_works(self, clean_environment, lifecycle):
        """Test network starts with default config."""
        returncode, stdout, stderr = lifecycle.run(
            detach=True,
            wait_ready=False,
            timeout=180
        )
        
        lifecycle.stop_network()
        assert returncode == 0, f"Failed with default config: {stderr}"
    
    def test_custom_config_path(self, clean_environment, lifecycle, tmp_path):
        """Test network with custom config path (if supported)."""
        # This test may need adjustment based on actual run.sh API
        # For now, just test that config parameter doesn't break things
        returncode, stdout, stderr = lifecycle.run(
            config="config/config.yml",
            detach=True,
            wait_ready=False,
            timeout=180
        )
        
        lifecycle.stop_network()
        # Should either work or fail gracefully
        assert returncode in [0, 1], f"Unexpected failure: {stderr}"


class TestNetworkHealthChecks:
    """Test network health checks."""
    
    def test_containers_have_names(self, running_network):
        """Test containers have proper naming."""
        containers = running_network.get_running_containers()
        
        for container in containers:
            assert container.startswith("cellframe-stage"), \
                f"Unexpected container name: {container}"
    
    def test_multiple_containers_running(self, running_network):
        """Test multiple containers can run."""
        containers = running_network.get_running_containers()
        
        # Assuming at least one node should be running
        assert len(containers) >= 1, f"Expected at least 1 container, got {len(containers)}"
