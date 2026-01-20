"""Unit tests for src/utils/cli.py."""

import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open, call
import sys

# Add stage-env root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.cli import (
    run_command,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_panel,
    print_table,
    confirm,
    format_duration,
    check_prerequisites,
    DualOutputConsole,
)


class TestRunCommand:
    """Test run_command function."""
    
    @patch('subprocess.run')
    def test_run_command_success(self, mock_run):
        """Test running command successfully."""
        mock_run.return_value = MagicMock(returncode=0, stdout="output", stderr="")
        
        exit_code, stdout, stderr = run_command(["echo", "test"])
        
        assert exit_code == 0
        assert stdout == "output"
        assert stderr == ""
        mock_run.assert_called_once()
    
    @patch('subprocess.run')
    def test_run_command_with_cwd(self, mock_run, tmp_path):
        """Test running command with custom working directory."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        run_command(["ls"], cwd=tmp_path)
        
        call_args = mock_run.call_args
        assert call_args[1]['cwd'] == tmp_path
    
    @patch('subprocess.run')
    def test_run_command_without_capture(self, mock_run):
        """Test running command without capturing output."""
        mock_run.return_value = MagicMock(returncode=0)
        
        exit_code, stdout, stderr = run_command(["echo", "test"], capture_output=False)
        
        assert exit_code == 0
        assert stdout == ""
        assert stderr == ""
    
    @patch('subprocess.run')
    def test_run_command_with_env(self, mock_run):
        """Test running command with custom environment."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        
        env = {"VAR": "value"}
        run_command(["echo"], env=env)
        
        call_args = mock_run.call_args
        assert call_args[1]['env'] == env
    
    @patch('subprocess.run')
    def test_run_command_failure_with_check(self, mock_run):
        """Test command failure with check=True."""
        mock_run.side_effect = subprocess.CalledProcessError(1, ["false"], stderr="error")
        
        with pytest.raises(subprocess.CalledProcessError):
            run_command(["false"], check=True)
    
    @patch('subprocess.run')
    def test_run_command_failure_without_check(self, mock_run):
        """Test command failure with check=False."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        
        exit_code, stdout, stderr = run_command(["false"], check=False)
        
        assert exit_code == 1
        assert stderr == "error"
    
    @patch('subprocess.run')
    def test_run_command_keyboard_interrupt(self, mock_run):
        """Test handling KeyboardInterrupt."""
        mock_run.side_effect = KeyboardInterrupt()
        
        with pytest.raises(KeyboardInterrupt):
            run_command(["sleep", "100"])


class TestFormatDuration:
    """Test format_duration function."""
    
    def test_format_seconds(self):
        """Test formatting duration in seconds."""
        assert format_duration(5.5) == "5.5s"
        assert format_duration(30.0) == "30.0s"
        assert format_duration(59.9) == "59.9s"
    
    def test_format_minutes(self):
        """Test formatting duration in minutes."""
        assert format_duration(60) == "1m 0s"
        assert format_duration(90) == "1m 30s"
        assert format_duration(3599) == "59m 59s"
    
    def test_format_hours(self):
        """Test formatting duration in hours."""
        assert format_duration(3600) == "1h 0m 0s"
        assert format_duration(3661) == "1h 1m 1s"
        assert format_duration(7265) == "2h 1m 5s"
    
    def test_format_zero(self):
        """Test formatting zero duration."""
        assert format_duration(0) == "0.0s"


class TestCheckPrerequisites:
    """Test check_prerequisites function."""
    
    @patch('subprocess.run')
    def test_check_prerequisites_all_present(self, mock_run):
        """Test when all prerequisites are present."""
        mock_run.return_value = MagicMock(returncode=0)
        
        result = check_prerequisites()
        
        assert result is True
        # Should check docker and python3
        assert mock_run.call_count == 2
    
    @patch('subprocess.run')
    def test_check_prerequisites_docker_missing(self, mock_run):
        """Test when docker is missing."""
        def side_effect(cmd, *args, **kwargs):
            if cmd[0] == "docker":
                raise FileNotFoundError()
            return MagicMock(returncode=0)
        
        mock_run.side_effect = side_effect
        
        result = check_prerequisites()
        
        assert result is False
    
    @patch('subprocess.run')
    def test_check_prerequisites_command_fails(self, mock_run):
        """Test when prerequisite command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(127, ["docker"])
        
        result = check_prerequisites()
        
        assert result is False


class TestConfirm:
    """Test confirm function."""
    
    @patch('src.utils.cli.console.input')
    def test_confirm_yes(self, mock_input):
        """Test confirming with 'yes'."""
        mock_input.return_value = "y"
        
        result = confirm("Proceed?")
        
        assert result is True
    
    @patch('src.utils.cli.console.input')
    def test_confirm_no(self, mock_input):
        """Test declining with 'no'."""
        mock_input.return_value = "n"
        
        result = confirm("Proceed?")
        
        assert result is False
    
    @patch('src.utils.cli.console.input')
    def test_confirm_default_true(self, mock_input):
        """Test default=True with empty input."""
        mock_input.return_value = ""
        
        result = confirm("Proceed?", default=True)
        
        assert result is True
    
    @patch('src.utils.cli.console.input')
    def test_confirm_default_false(self, mock_input):
        """Test default=False with empty input."""
        mock_input.return_value = ""
        
        result = confirm("Proceed?", default=False)
        
        assert result is False
    
    @patch('src.utils.cli.console.input')
    def test_confirm_case_insensitive(self, mock_input):
        """Test that confirm is case insensitive."""
        mock_input.return_value = "Y"
        assert confirm("Proceed?") is True
        
        mock_input.return_value = "YES"
        assert confirm("Proceed?") is True
        
        mock_input.return_value = "yes"
        assert confirm("Proceed?") is True


class TestDualOutputConsole:
    """Test DualOutputConsole class."""
    
    def test_init(self):
        """Test DualOutputConsole initialization."""
        console = DualOutputConsole()
        
        assert console.console is not None
        assert console._log_file is None
    
    @patch('src.utils.cli.get_log_file')
    @patch('builtins.open', new_callable=mock_open)
    def test_print_with_log_file(self, mock_file, mock_get_log_file, tmp_path):
        """Test printing with log file enabled."""
        log_file = tmp_path / "test.log"
        mock_get_log_file.return_value = log_file
        
        console = DualOutputConsole()
        console.print("test message")
        
        # Should attempt to write to log file
        mock_file.assert_called()
    
    @patch('src.utils.cli.get_log_file')
    def test_print_without_log_file(self, mock_get_log_file):
        """Test printing without log file."""
        mock_get_log_file.return_value = None
        
        console = DualOutputConsole()
        # Should not raise even without log file
        console.print("test message")
    
    def test_delegate_attributes(self):
        """Test that DualOutputConsole delegates attributes to console."""
        dual_console = DualOutputConsole()
        
        # Should have console attributes
        assert hasattr(dual_console, 'width')
        assert hasattr(dual_console, 'height')


class TestPrintFunctions:
    """Test print utility functions."""
    
    @patch('src.utils.cli.console.print')
    def test_print_success(self, mock_print):
        """Test print_success function."""
        print_success("Operation completed")
        
        mock_print.assert_called_once()
        call_args = mock_print.call_args[0][0]
        assert "✓" in call_args
        assert "Operation completed" in call_args
    
    @patch('src.utils.cli.console.print')
    def test_print_error(self, mock_print):
        """Test print_error function."""
        print_error("Operation failed")
        
        mock_print.assert_called_once()
        call_args = mock_print.call_args[0][0]
        assert "✗" in call_args
        assert "Operation failed" in call_args
    
    @patch('src.utils.cli.console.print')
    def test_print_warning(self, mock_print):
        """Test print_warning function."""
        print_warning("Be careful")
        
        mock_print.assert_called_once()
        call_args = mock_print.call_args[0][0]
        assert "⚠" in call_args
        assert "Be careful" in call_args
    
    @patch('src.utils.cli.console.print')
    def test_print_info(self, mock_print):
        """Test print_info function."""
        print_info("Information")
        
        mock_print.assert_called_once()
        call_args = mock_print.call_args[0][0]
        assert "•" in call_args
        assert "Information" in call_args
    
    @patch('src.utils.cli.console.print')
    def test_print_panel(self, mock_print):
        """Test print_panel function."""
        print_panel("Title", "Content", style="blue")
        
        mock_print.assert_called_once()
        # Panel should be in the call
        from rich.panel import Panel
        assert isinstance(mock_print.call_args[0][0], Panel)
    
    @patch('src.utils.cli.console.print')
    def test_print_table(self, mock_print):
        """Test print_table function."""
        columns = ["Name", "Value"]
        rows = [["item1", "val1"], ["item2", "val2"]]
        
        print_table("Test Table", columns, rows)
        
        mock_print.assert_called_once()
        # Table should be in the call
        from rich.table import Table
        assert isinstance(mock_print.call_args[0][0], Table)


class TestDualOutputConsoleIntegration:
    """Integration tests for DualOutputConsole."""
    
    @patch('src.utils.cli.get_log_file')
    def test_write_to_log_strips_ansi(self, mock_get_log_file, tmp_path):
        """Test that writing to log strips ANSI codes."""
        log_file = tmp_path / "test.log"
        log_file.touch()
        mock_get_log_file.return_value = log_file
        
        console = DualOutputConsole()
        # Manually call _write_to_log with ANSI codes
        console._write_to_log("\x1b[31mRed text\x1b[0m")
        
        # Read log file and verify ANSI codes are stripped
        content = log_file.read_text()
        assert "\x1b[" not in content
        assert "Red text" in content
    
    @patch('src.utils.cli.get_log_file')
    def test_write_to_log_handles_exceptions(self, mock_get_log_file):
        """Test that write_to_log handles exceptions gracefully."""
        mock_get_log_file.return_value = Path("/invalid/path/test.log")
        
        console = DualOutputConsole()
        # Should not raise even with invalid log path
        console._write_to_log("test")
