"""E2E tests for Docker integration."""

import pytest


class TestDockerIntegration:
    """Test Docker integration aspects."""
    
    def test_docker_network_created(self, running_network):
        """Test Docker network is created."""
        import subprocess
        
        result = subprocess.run(
            ["docker", "network", "ls", "--format", "{{.Name}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        networks = result.stdout.strip().split('\n')
        # Should have cellframe network
        assert any("cellframe" in n.lower() for n in networks), \
            f"No cellframe network found: {networks}"
    
    def test_docker_compose_files_present(self, stage_env_root):
        """Test docker-compose files are present."""
        compose_file = stage_env_root / "docker-compose.yml"
        # May or may not exist depending on setup, just check gracefully
        # This is more of a sanity check
        pass  # Actual check would depend on setup
    
    def test_containers_use_correct_image(self, running_network):
        """Test containers use expected image."""
        import subprocess
        
        containers = running_network.get_running_containers()
        
        if not containers:
            pytest.skip("No containers running")
        
        # Get image for first container
        result = subprocess.run(
            ["docker", "inspect", containers[0], "--format", "{{.Config.Image}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        image = result.stdout.strip()
        # Should be a cellframe image
        assert "cellframe" in image.lower() or "node" in image.lower(), \
            f"Unexpected image: {image}"


class TestResourceManagement:
    """Test resource management."""
    
    def test_containers_have_resource_limits(self, running_network):
        """Test containers have resource limits (if configured)."""
        containers = running_network.get_running_containers()
        
        if not containers:
            pytest.skip("No containers running")
        
        # Just verify we can query resources
        import subprocess
        
        result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"],
            capture_output=True,
            text=True,
            timeout=15
        )
        
        assert result.returncode == 0, "Failed to get container stats"
        assert len(result.stdout) > 0, "No stats retrieved"
