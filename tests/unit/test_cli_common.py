"""Unit tests for src/cli/common.py."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.cli.common import (
    print_info, print_success, print_error, print_warning,
    format_duration, check_prerequisites, setup_logging
)

class TestPrintFunctions:
    """Test print helper functions."""
    
    @patch('src.cli.common.console')
    def test_print_info(self, mock_console):
        """Test print_info."""
        print_info("test message")
        mock_console.print.assert_called_once()
    
    @patch('src.cli.common.console')
    def test_print_success(self, mock_console):
        """Test print_success."""
        print_success("success")
        mock_console.print.assert_called_once()
    
    @patch('src.cli.common.console')
    def test_print_error(self, mock_console):
        """Test print_error."""
        print_error("error")
        mock_console.print.assert_called_once()

class TestFormatDuration:
    """Test format_duration helper."""
    
    def test_format_milliseconds(self):
        """Test formatting milliseconds."""
        result = format_duration(0.5)
        assert "ms" in result
    
    def test_format_seconds(self):
        """Test formatting seconds."""
        result = format_duration(45.5)
        assert "s" in result
    
    def test_format_minutes(self):
        """Test formatting minutes."""
        result = format_duration(125)
        assert "m" in result

class TestCheckPrerequisites:
    """Test check_prerequisites."""
    
    @patch('shutil.which')
    @patch('subprocess.run')
    def test_check_prerequisites_all_present(self, mock_run, mock_which):
        """Test when all prerequisites are present."""
        mock_which.return_value = "/usr/bin/docker"
        mock_run.return_value = MagicMock(returncode=0)
        assert check_prerequisites() is True
    
    @patch('shutil.which')
    def test_check_prerequisites_missing_docker(self, mock_which):
        """Test when Docker is missing."""
        mock_which.return_value = None
        assert check_prerequisites() is False

class TestSetupLogging:
    """Test setup_logging wrapper."""
    
    @patch('src.utils.logger.setup_logging')
    def test_setup_logging_default(self, mock_setup, tmp_path):
        """Test setup_logging with defaults."""
        setup_logging()
        mock_setup.assert_called_once()
