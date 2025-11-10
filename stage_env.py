#!/usr/bin/env python3
"""
Stage Environment CLI - управление тестовым окружением Cellframe Node.

"""

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.logger import setup_logging, get_logger

# Initialize CLI app
app = typer.Typer(
    name="stage_env",
    help="🚀 Cellframe Node Stage Environment Manager",
    add_completion=False,
)

console = Console()
logger = get_logger(__name__)

# Global state
BASE_PATH = Path(__file__).parent
CONFIG_PATH: Optional[Path] = None


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable verbose logging"),
    json_logs: bool = typer.Option(False, "--json", help="Output logs as JSON"),
    config: Optional[str] = typer.Option(None, "--config", help="Path to stage-env.cfg"),
):
    """Configure global options."""
    global CONFIG_PATH
    
    # Set config path from option or environment variable
    if config:
        CONFIG_PATH = Path(config).resolve()
    else:
        import os
        env_config = os.environ.get("STAGE_ENV_CONFIG")
        if env_config:
            CONFIG_PATH = Path(env_config).resolve()
    
    # Initialize global configuration manager FIRST (before reading config for logging)
    from src.config.manager import initialize_config
    initialize_config(BASE_PATH, CONFIG_PATH)
    
    # Setup logging with file output using centralized config manager
    log_file = None
    try:
        from src.config.manager import get_config_loader
        config_loader = get_config_loader()
        # Try to load config for logging setup (may fail if config doesn't exist)
        try:
            stage_config = config_loader.load_stage_config()
            if 'log_dir' in stage_config:
                log_dir = BASE_PATH / stage_config['log_dir']
                log_dir.mkdir(parents=True, exist_ok=True)
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                log_file = log_dir / f"stage-env_{timestamp}.log"
        except FileNotFoundError:
            # Config not found - will use defaults, no file logging
            pass
    except Exception as e:
        print(f"Warning: Failed to setup file logging: {e}", file=sys.stderr)
    
    setup_logging(verbose=verbose, json_output=json_logs, log_file=log_file)
    
    if log_file:
        logger.info("file_logging_enabled", log_file=str(log_file))


# Register commands from modules
from src.cli import (
    cert_commands,
    network_commands,
    test_commands,
    snapshot_commands,
)

# Helper function to get current config path
def get_config_path():
    return CONFIG_PATH

cert_commands.register_commands(app, BASE_PATH, get_config_path)
network_commands.register_commands(app, BASE_PATH, get_config_path)
test_commands.register_commands(app, BASE_PATH, get_config_path)
snapshot_commands.register_commands(app, BASE_PATH, get_config_path)


if __name__ == "__main__":
    app()
