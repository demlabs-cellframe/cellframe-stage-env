"""Global Pytest configuration for stage-env tests."""

import sys
import os
from pathlib import Path
import pytest

# Add stage-env root to Python path so we can import src.*
STAGE_ENV_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(STAGE_ENV_ROOT))

@pytest.fixture(scope="session")
def stage_env_root():
    """Return the root path of stage-env."""
    return STAGE_ENV_ROOT

@pytest.fixture(scope="session")
def fixtures_dir(stage_env_root):
    """Return the path to shared fixtures."""
    return stage_env_root / "tests" / "unit" / "fixtures"

