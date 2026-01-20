"""Unit tests for src/utils/pid_manager.py."""

import pytest
import os
import signal
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import sys

# Add stage-env root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.pid_manager import PIDManager


class TestPIDManagerInit:
    """Test PIDManager initialization."""
    
    def test_init_creates_pid_file_path(self, tmp_path):
        """Test that __init__ creates correct PID file path."""
        manager = PIDManager(tmp_path)
        
        assert manager.base_path == tmp_path
        assert manager.pid_file == tmp_path / ".stage-env.pid"
        assert manager.pid == os.getpid()
    
    def test_init_with_nested_path(self, tmp_path):
        """Test init with nested directory path."""
        nested_path = tmp_path / "subdir" / "stage-env"
        manager = PIDManager(nested_path)
        
        assert manager.pid_file == nested_path / ".stage-env.pid"


class TestPIDManagerCheckAndCreate:
    """Test check_and_create method."""
    
    def test_check_and_create_no_existing_file(self, tmp_path):
        """Test check_and_create when no PID file exists."""
        manager = PIDManager(tmp_path)
        
        result = manager.check_and_create()
        
        assert result is True
        assert manager.pid_file.exists()
        
        # Verify PID file contains current PID
        assert manager.pid_file.read_text() == str(os.getpid())
    
    def test_check_and_create_with_stale_pid(self, tmp_path):
        """Test check_and_create with stale PID file."""
        manager = PIDManager(tmp_path)
        
        # Create PID file with non-existent PID
        stale_pid = 999999
        manager.pid_file.write_text(str(stale_pid))
        
        with patch.object(PIDManager, '_is_process_running', return_value=False):
            result = manager.check_and_create()
        
        assert result is True
        assert manager.pid_file.exists()
        assert manager.pid_file.read_text() == str(os.getpid())
    
    def test_check_and_create_with_running_process(self, tmp_path):
        """Test check_and_create when another instance is running."""
        manager = PIDManager(tmp_path)
        
        # Create PID file with "running" PID
        running_pid = 12345
        manager.pid_file.write_text(str(running_pid))
        
        with patch.object(PIDManager, '_is_process_running', return_value=True):
            result = manager.check_and_create()
        
        assert result is False
        # Original PID should still be in file
        assert manager.pid_file.read_text() == str(running_pid)
    
    def test_check_and_create_with_invalid_pid_file(self, tmp_path):
        """Test check_and_create with invalid PID file content."""
        manager = PIDManager(tmp_path)
        
        # Create invalid PID file
        manager.pid_file.write_text("invalid_pid")
        
        result = manager.check_and_create()
        
        assert result is True
        assert manager.pid_file.read_text() == str(os.getpid())
    
    def test_check_and_create_file_creation_fails(self, tmp_path):
        """Test check_and_create when file creation fails."""
        manager = PIDManager(tmp_path)
        
        with patch("builtins.open", side_effect=OSError("Permission denied")):
            result = manager.check_and_create()
        
        assert result is False


class TestPIDManagerGetRunningPid:
    """Test get_running_pid method."""
    
    def test_get_running_pid_no_file(self, tmp_path):
        """Test get_running_pid when no PID file exists."""
        manager = PIDManager(tmp_path)
        
        result = manager.get_running_pid()
        
        assert result is None
    
    def test_get_running_pid_with_running_process(self, tmp_path):
        """Test get_running_pid with running process."""
        manager = PIDManager(tmp_path)
        
        running_pid = 12345
        manager.pid_file.write_text(str(running_pid))
        
        with patch.object(PIDManager, '_is_process_running', return_value=True):
            result = manager.get_running_pid()
        
        assert result == running_pid
    
    def test_get_running_pid_with_stale_file(self, tmp_path):
        """Test get_running_pid with stale PID file."""
        manager = PIDManager(tmp_path)
        
        manager.pid_file.write_text("999999")
        
        with patch.object(PIDManager, '_is_process_running', return_value=False):
            result = manager.get_running_pid()
        
        assert result is None
    
    def test_get_running_pid_with_invalid_file(self, tmp_path):
        """Test get_running_pid with invalid PID file."""
        manager = PIDManager(tmp_path)
        
        manager.pid_file.write_text("invalid")
        
        result = manager.get_running_pid()
        
        assert result is None


class TestPIDManagerRemove:
    """Test remove method."""
    
    def test_remove_own_pid_file(self, tmp_path):
        """Test removing our own PID file."""
        manager = PIDManager(tmp_path)
        
        # Create PID file
        manager.check_and_create()
        assert manager.pid_file.exists()
        
        # Remove it
        manager.remove()
        assert not manager.pid_file.exists()
    
    def test_remove_does_not_remove_other_pid(self, tmp_path):
        """Test that remove doesn't remove another process's PID file."""
        manager = PIDManager(tmp_path)
        
        # Create PID file with different PID
        other_pid = 99999
        manager.pid_file.write_text(str(other_pid))
        
        manager.remove()
        
        # File should still exist
        assert manager.pid_file.exists()
        assert manager.pid_file.read_text() == str(other_pid)
    
    def test_remove_non_existent_file(self, tmp_path):
        """Test removing non-existent PID file."""
        manager = PIDManager(tmp_path)
        
        # Should not raise
        manager.remove()
    
    def test_remove_with_invalid_file(self, tmp_path):
        """Test remove with invalid PID file content."""
        manager = PIDManager(tmp_path)
        
        manager.pid_file.write_text("invalid")
        
        # Should not raise
        manager.remove()
        
        # File should still exist (wasn't ours)
        assert manager.pid_file.exists()


class TestPIDManagerIsProcessRunning:
    """Test _is_process_running static method."""
    
    def test_is_process_running_with_own_pid(self):
        """Test _is_process_running with current process."""
        result = PIDManager._is_process_running(os.getpid())
        
        assert result is True
    
    def test_is_process_running_with_non_existent_pid(self):
        """Test _is_process_running with non-existent PID."""
        # Use a very high PID that's unlikely to exist
        result = PIDManager._is_process_running(999999)
        
        assert result is False
    
    @patch('os.kill')
    def test_is_process_running_with_permission_error(self, mock_kill):
        """Test _is_process_running when permission is denied."""
        # OSError with errno != ESRCH means process exists but we can't signal it
        mock_kill.side_effect = OSError("Operation not permitted")
        
        result = PIDManager._is_process_running(12345)
        
        assert result is False


class TestPIDManagerContextManager:
    """Test context manager functionality."""
    
    def test_context_manager_creates_and_removes_pid_file(self, tmp_path):
        """Test context manager creates and removes PID file."""
        manager = PIDManager(tmp_path)
        
        with manager:
            assert manager.pid_file.exists()
            assert manager.pid_file.read_text() == str(os.getpid())
        
        # PID file should be removed
        assert not manager.pid_file.exists()
    
    def test_context_manager_raises_if_already_running(self, tmp_path):
        """Test context manager raises if another instance is running."""
        manager = PIDManager(tmp_path)
        
        # Create PID file with "running" process
        manager.pid_file.write_text("12345")
        
        with patch.object(PIDManager, '_is_process_running', return_value=True):
            with pytest.raises(RuntimeError, match="Another instance of stage-env is already running"):
                with manager:
                    pass
    
    def test_context_manager_removes_pid_on_exception(self, tmp_path):
        """Test context manager removes PID file even on exception."""
        manager = PIDManager(tmp_path)
        
        try:
            with manager:
                assert manager.pid_file.exists()
                raise ValueError("Test exception")
        except ValueError:
            pass
        
        # PID file should still be removed
        assert not manager.pid_file.exists()
    
    def test_context_manager_doesnt_remove_other_pid(self, tmp_path):
        """Test context manager doesn't remove another process's PID."""
        manager1 = PIDManager(tmp_path)
        manager2 = PIDManager(tmp_path)
        
        # Create with first manager
        with manager1:
            pass
        
        # Create PID file manually with different PID
        manager2.pid_file.write_text("99999")
        
        # Try to exit with manager1 (but PID doesn't match)
        manager1.remove()
        
        # File should still exist
        assert manager2.pid_file.exists()


class TestPIDManagerIntegration:
    """Integration tests for PIDManager."""
    
    def test_sequential_instances(self, tmp_path):
        """Test running instances sequentially."""
        # First instance
        with PIDManager(tmp_path):
            pass
        
        # Second instance should succeed
        with PIDManager(tmp_path):
            pass
    
    def test_check_running_instance(self, tmp_path):
        """Test checking for running instance."""
        manager1 = PIDManager(tmp_path)
        
        with manager1:
            # Create second manager
            manager2 = PIDManager(tmp_path)
            
            # Should detect running instance
            running_pid = manager2.get_running_pid()
            assert running_pid == os.getpid()
    
    def test_stale_pid_file_recovery(self, tmp_path):
        """Test recovery from stale PID file."""
        manager = PIDManager(tmp_path)
        
        # Simulate stale PID file
        manager.pid_file.write_text("999999")
        
        # Should recover and create new instance
        with manager:
            assert manager.pid_file.read_text() == str(os.getpid())
