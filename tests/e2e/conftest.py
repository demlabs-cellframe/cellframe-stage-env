"""Pytest fixtures for E2E tests."""

import pytest
from pathlib import Path
import sys

# Add stage-env root to path
STAGE_ENV_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(STAGE_ENV_ROOT))

from tests.e2e.helpers import StageEnvLifecycle


@pytest.fixture(scope="session")
def stage_env_root():
    """Return stage-env root directory."""
    return STAGE_ENV_ROOT


@pytest.fixture(scope="session")
def lifecycle(stage_env_root):
    """Create StageEnvLifecycle instance."""
    return StageEnvLifecycle(stage_env_root)


@pytest.fixture(scope="function")
def clean_environment(lifecycle):
    """Ensure clean environment before test."""
    # Clean before test
    returncode, stdout, stderr = lifecycle.clean()
    if returncode != 0:
        pytest.skip(f"Failed to clean environment: {stderr}")
    
    yield
    
    # Clean after test
    lifecycle.clean()


@pytest.fixture(scope="function")
def running_network(lifecycle, clean_environment):
    """Provide a running network."""
    # Start network
    returncode, stdout, stderr = lifecycle.run(
        detach=True,
        wait_ready=True,
        timeout=180
    )
    
    if returncode != 0:
        pytest.skip(f"Failed to start network: {stderr}")
    
    # Wait for network to be ready
    if not lifecycle.wait_for_network_ready(timeout=90):
        lifecycle.stop_network()
        pytest.skip("Network not ready in time")
    
    yield lifecycle
    
    # Stop network after test
    lifecycle.stop_network()


@pytest.fixture(scope="function")
def network_containers(running_network):
    """Get list of running containers."""
    return running_network.get_running_containers()
