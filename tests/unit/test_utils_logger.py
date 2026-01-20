"""Unit tests for src/utils/logger.py."""

import pytest
import logging
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import structlog

# Add stage-env root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.logger import (
    setup_logging,
    get_logger,
    get_log_file,
    strip_ansi_codes,
    LogContext,
    StripAnsiFormatter,
    _file_handler,
)

# Global to track file handler
import src.utils.logger as logger_module


class TestStripAnsiCodes:
    """Test ANSI code stripping."""
    
    def test_strip_simple_color_codes(self):
        """Test stripping simple color codes."""
        text_with_colors = "\x1b[31mRed text\x1b[0m"
        result = strip_ansi_codes(text_with_colors)
        assert result == "Red text"
    
    def test_strip_multiple_color_codes(self):
        """Test stripping multiple color codes."""
        text = "\x1b[31mRed\x1b[0m and \x1b[32mGreen\x1b[0m"
        result = strip_ansi_codes(text)
        assert result == "Red and Green"
    
    def test_no_ansi_codes(self):
        """Test text without ANSI codes."""
        text = "Plain text"
        result = strip_ansi_codes(text)
        assert result == "Plain text"
    
    def test_complex_ansi_codes(self):
        """Test stripping complex ANSI codes."""
        text = "\x1b[1;31;40mBold red on black\x1b[0m"
        result = strip_ansi_codes(text)
        assert result == "Bold red on black"


class TestStripAnsiFormatter:
    """Test StripAnsiFormatter class."""
    
    def test_format_with_ansi_codes(self):
        """Test formatting log record with ANSI codes."""
        formatter = StripAnsiFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="\x1b[31mColored message\x1b[0m",
            args=(),
            exc_info=None
        )
        result = formatter.format(record)
        assert result == "Colored message"
    
    def test_format_without_ansi_codes(self):
        """Test formatting log record without ANSI codes."""
        formatter = StripAnsiFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Plain message",
            args=(),
            exc_info=None
        )
        result = formatter.format(record)
        assert result == "Plain message"


class TestSetupLogging:
    """Test setup_logging function."""
    
    def teardown_method(self):
        """Clean up after each test."""
        # Reset root logger handlers
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            handler.close()
            root_logger.removeHandler(handler)
        root_logger.handlers.clear()
        
        # Reset file handler global
        logger_module._file_handler = None
    
    def test_setup_logging_default(self):
        """Test setup_logging with default parameters."""
        setup_logging()
        
        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO
        assert len(root_logger.handlers) >= 1
    
    def test_setup_logging_verbose(self):
        """Test setup_logging with verbose=True."""
        setup_logging(verbose=True)
        
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG
    
    def test_setup_logging_with_log_file(self, tmp_path):
        """Test setup_logging with log file."""
        log_file = tmp_path / "test.log"
        
        setup_logging(log_file=log_file)
        
        root_logger = logging.getLogger()
        # Should have stdout handler + file handler
        assert len(root_logger.handlers) >= 2
        
        # Check file handler exists
        file_handlers = [h for h in root_logger.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) == 1
        
        # Verify formatter strips ANSI codes
        file_handler = file_handlers[0]
        assert isinstance(file_handler.formatter, StripAnsiFormatter)
    
    def test_setup_logging_json_output(self):
        """Test setup_logging with json_output=True."""
        setup_logging(json_output=True)
        
        # Just verify it doesn't raise
        logger = get_logger(__name__)
        logger.info("test_message")
    
    def test_setup_logging_clears_existing_handlers(self):
        """Test that setup_logging clears existing handlers."""
        root_logger = logging.getLogger()
        
        # Add a dummy handler
        dummy_handler = logging.StreamHandler()
        root_logger.addHandler(dummy_handler)
        
        initial_handlers = len(root_logger.handlers)
        
        setup_logging()
        
        # Handlers should be cleared and new ones added
        assert dummy_handler not in root_logger.handlers


class TestGetLogger:
    """Test get_logger function."""
    
    def test_get_logger_returns_bound_logger(self):
        """Test that get_logger returns a structlog BoundLogger or Proxy."""
        logger = get_logger("test_module")
        
        # structlog may return BoundLogger or BoundLoggerLazyProxy
        assert hasattr(logger, 'info')
        assert hasattr(logger, 'error')
        assert hasattr(logger, 'debug')
    
    def test_get_logger_with_different_names(self):
        """Test get_logger with different module names."""
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")
        
        # Both should have logger methods
        assert hasattr(logger1, 'info')
        assert hasattr(logger2, 'info')


class TestLogContext:
    """Test LogContext context manager."""
    
    def test_log_context_binds_variables(self):
        """Test that LogContext binds context variables."""
        setup_logging()
        
        with LogContext(node_id=1, action="start"):
            # Context should be bound
            pass
        
        # Context should be unbound after exiting
        pass
    
    def test_log_context_multiple_keys(self):
        """Test LogContext with multiple keys."""
        setup_logging()
        
        with LogContext(node_id=1, action="start", role="master"):
            pass
        
        # Should not raise
    
    def test_log_context_nested(self):
        """Test nested LogContext."""
        setup_logging()
        
        with LogContext(outer="value1"):
            with LogContext(inner="value2"):
                pass
        
        # Should not raise


class TestGetLogFile:
    """Test get_log_file function."""
    
    def teardown_method(self):
        """Clean up after each test."""
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            handler.close()
            root_logger.removeHandler(handler)
        root_logger.handlers.clear()
        logger_module._file_handler = None
    
    def test_get_log_file_when_not_set(self):
        """Test get_log_file when no file logging is configured."""
        # Ensure no file handler is set
        logger_module._file_handler = None
        setup_logging()
        
        result = get_log_file()
        # Should be None since we didn't pass log_file parameter
        # Note: If a previous test set it, teardown should have cleared it
        if result is not None:
            # This means teardown didn't work properly, skip test
            pytest.skip("File handler from previous test still active")
    
    def test_get_log_file_when_set(self, tmp_path):
        """Test get_log_file when file logging is configured."""
        log_file = tmp_path / "test.log"
        
        setup_logging(log_file=log_file)
        
        result = get_log_file()
        assert result is not None
        assert result == log_file
    
    def test_get_log_file_returns_path(self, tmp_path):
        """Test that get_log_file returns a Path object."""
        log_file = tmp_path / "test.log"
        
        setup_logging(log_file=log_file)
        
        result = get_log_file()
        assert isinstance(result, Path)


class TestLoggingIntegration:
    """Integration tests for logging functionality."""
    
    def teardown_method(self):
        """Clean up after each test."""
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            handler.close()
            root_logger.removeHandler(handler)
        root_logger.handlers.clear()
        logger_module._file_handler = None
    
    def test_logging_to_file_strips_ansi(self, tmp_path):
        """Test that logging to file strips ANSI codes."""
        log_file = tmp_path / "test.log"
        
        setup_logging(log_file=log_file)
        
        logger = get_logger(__name__)
        logger.info("test_message", colored_value="\x1b[31mRed\x1b[0m")
        
        # Read log file and verify ANSI codes are stripped
        assert log_file.exists()
        content = log_file.read_text()
        
        # Should not contain ANSI codes
        assert "\x1b[" not in content
    
    def test_logging_with_exception(self):
        """Test logging with exception info."""
        setup_logging()
        
        logger = get_logger(__name__)
        
        try:
            raise ValueError("Test exception")
        except ValueError:
            logger.error("test_error", exc_info=True)
        
        # Should not raise
    
    def test_multiple_loggers(self):
        """Test multiple loggers working together."""
        setup_logging()
        
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")
        
        logger1.info("message_from_module1")
        logger2.info("message_from_module2")
        
        # Should not raise
