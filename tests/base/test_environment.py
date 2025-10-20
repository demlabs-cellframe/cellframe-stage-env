"""
Base tests for stage environment.

These tests verify that the stage environment is correctly set up
and can be used by external projects.
"""

import subprocess
from pathlib import Path


def test_stage_env_cli_available():
    """Test that stage_env.py CLI is available."""
    stage_env = Path(__file__).parent.parent.parent / "stage_env.py"
    assert stage_env.exists(), "stage_env.py not found"
    assert stage_env.stat().st_mode & 0o111, "stage_env.py is not executable"


def test_stage_env_help():
    """Test that stage-env --help works."""
    stage_env = Path(__file__).parent.parent.parent / "stage-env"
    
    result = subprocess.run(
        [str(stage_env), "--help"],
        capture_output=True,
        text=True,
    )
    
    assert result.returncode == 0, "stage-env --help failed"
    assert "Stage Environment" in result.stdout or "stage_env" in result.stdout


def test_python_modules_importable():
    """Test that all Python modules can be imported."""
    # This test verifies the module structure
    import sys
    from pathlib import Path
    
    src_dir = Path(__file__).parent.parent.parent / "src"
    sys.path.insert(0, str(src_dir.parent))
    
    # Try importing key modules
    try:
        from src.utils import logger, cli
        from src.config import loader
        from src.docker import compose
        from src.monitoring import health
        from src.network import manager
        from src.build import builder
        from src.certs import generator
    except ImportError as e:
        assert False, f"Failed to import module: {e}"


def test_requirements_file_exists():
    """Test that requirements.txt exists."""
    requirements = Path(__file__).parent.parent.parent / "requirements.txt"
    assert requirements.exists(), "requirements.txt not found"
    
    # Check that it has content
    content = requirements.read_text()
    assert len(content) > 0, "requirements.txt is empty"
    assert "typer" in content, "typer not in requirements"
    assert "docker" in content, "docker not in requirements"

