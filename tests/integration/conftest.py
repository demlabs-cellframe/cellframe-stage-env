"""
Integration tests fixtures and configuration.
"""
import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def temp_base_path(tmp_path):
    """
    Provides a temporary base path for integration tests.
    
    This fixture creates a temporary directory that mimics the structure
    expected by stage-env components.
    """
    base = tmp_path / "stage-env-test"
    base.mkdir(parents=True, exist_ok=True)
    
    # Create expected subdirectories
    (base / "config").mkdir(exist_ok=True)
    (base / "logs").mkdir(exist_ok=True)
    (base / "cache").mkdir(exist_ok=True)
    (base / "artifacts").mkdir(exist_ok=True)
    (base / "snapshots").mkdir(exist_ok=True)
    
    return base
