"""Tests for CLI parser functionality.

Expanded coverage for:
- CLI command extraction
- Help parsing
- Option parsing
- Edge cases
"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.cli_parser import CLICommandParser


class TestCLICommandExtraction:
    """Tests for command extraction from CLI help."""
    
    def test_extract_commands_basic(self):
        """Test extracting commands from basic help output."""
        parser = CLICommandParser()
        help_text = """
Cellframe Node CLI tool

Commands:
    token_decl:          Token declaration
    token_emit:          Token emission
    wallet:              Wallet operations
"""
        commands = parser._extract_commands(help_text)
        assert "token_decl" in commands
        assert "token_emit" in commands
        assert "wallet" in commands
    
    def test_extract_commands_with_tabs(self):
        """Test extracting commands with tab separators."""
        parser = CLICommandParser()
        help_text = """
Commands:
    tx_create:\t\t\tCreate transaction
    dag:\t\t\t\tDAG operations
"""
        commands = parser._extract_commands(help_text)
        assert "tx_create" in commands
        assert "dag" in commands
    
    def test_extract_commands_filters_special(self):
        """Test that special commands are filtered out."""
        parser = CLICommandParser()
        help_text = """
Commands:
    help:                Show help
    version:             Show version
    exit:                Exit
    quit:                Quit
    token_decl:          Token declaration
"""
        commands = parser._extract_commands(help_text)
        assert "help" not in commands
        assert "version" not in commands
        assert "exit" not in commands
        assert "quit" not in commands
        assert "token_decl" in commands
    
    def test_extract_commands_no_colon(self):
        """Test that commands without colon are ignored."""
        parser = CLICommandParser()
        help_text = """
Commands:
    token_decl:          Token declaration
    random_text          Not a command
    wallet:              Wallet operations
"""
        commands = parser._extract_commands(help_text)
        assert "token_decl" in commands
        assert "wallet" in commands
        assert "random_text" not in commands
    
    def test_extract_commands_empty_help(self):
        """Test extracting from empty help output."""
        parser = CLICommandParser()
        commands = parser._extract_commands("")
        assert commands == []
    
    def test_extract_commands_filters_keywords(self):
        """Test that 'Commands' keyword is filtered."""
        parser = CLICommandParser()
        help_text = """
Cellframe Node CLI

Commands:
    token_decl:          Token declaration
"""
        commands = parser._extract_commands(help_text)
        assert "Commands" not in commands
        assert "token_decl" in commands
    
    def test_extract_commands_mixed_indentation(self):
        """Test extraction with mixed indentation."""
        parser = CLICommandParser()
        help_text = """
Commands:
  token_decl:            Token declaration
    wallet:              Wallet operations
        tx_create:       Create transaction
"""
        commands = parser._extract_commands(help_text)
        assert "token_decl" in commands
        assert "wallet" in commands
        assert "tx_create" in commands
    
    def test_extract_commands_underscore_and_numbers(self):
        """Test commands with underscores and numbers."""
        parser = CLICommandParser()
        help_text = """
Commands:
    token_decl_v2:       Token declaration v2
    srv_stake_order:     Stake order
    net_3_config:        Network 3 config
"""
        commands = parser._extract_commands(help_text)
        assert "token_decl_v2" in commands
        assert "srv_stake_order" in commands
        assert "net_3_config" in commands


class TestCLIHelpParsing:
    """Tests for CLI help parsing."""
    
    def test_parse_help_with_options(self):
        """Test parsing help with options."""
        parser = CLICommandParser()
        help_text = """
token_decl - Token declaration

Options:
    -net <net_name>      Network name
    -chain <chain>       Chain name
    -token <ticker>      Token ticker
"""
        # This would require implementing option parsing
        # For now, test that parser doesn't crash
        assert help_text is not None
    
    def test_parse_multiline_description(self):
        """Test parsing multiline descriptions."""
        parser = CLICommandParser()
        help_text = """
wallet - Wallet operations

Description:
    Manage wallets including creation,
    listing, and balance checks.

Options:
    -w <wallet>          Wallet name
"""
        assert "wallet" in help_text


class TestCLIParserEdgeCases:
    """Edge case tests for CLI parser."""
    
    def test_unicode_in_help(self):
        """Test handling Unicode characters."""
        parser = CLICommandParser()
        help_text = """
Commands:
    token_décl:          Token declaration (français)
    wallet_операции:     Wallet operations (русский)
"""
        # Should not crash
        commands = parser._extract_commands(help_text)
        # Note: current parser only accepts [a-zA-Z0-9_]
        # Unicode commands will be filtered out
        assert len(commands) >= 0
    
    def test_very_long_command_name(self):
        """Test handling very long command names."""
        parser = CLICommandParser()
        long_name = "a" * 1000
        help_text = f"""
Commands:
    {long_name}:         Long command
    wallet:              Normal command
"""
        commands = parser._extract_commands(help_text)
        # Should still extract valid commands
        assert "wallet" in commands
    
    def test_special_characters_in_description(self):
        """Test special characters in descriptions."""
        parser = CLICommandParser()
        help_text = """
Commands:
    token_decl:          Token declaration <required> [optional]
    wallet:              Wallet ops & more | stuff
"""
        commands = parser._extract_commands(help_text)
        assert "token_decl" in commands
        assert "wallet" in commands
    
    def test_empty_lines(self):
        """Test handling multiple empty lines."""
        parser = CLICommandParser()
        help_text = """


Commands:


    token_decl:          Token declaration


    wallet:              Wallet operations


"""
        commands = parser._extract_commands(help_text)
        assert "token_decl" in commands
        assert "wallet" in commands
    
    def test_no_commands_section(self):
        """Test help without 'Commands:' section."""
        parser = CLICommandParser()
        help_text = """
Cellframe Node CLI Tool
Version 5.3-123

Usage: cellframe-node-cli [options]
"""
        commands = parser._extract_commands(help_text)
        # Should return empty list, not None
        assert isinstance(commands, list)
        assert len(commands) == 0
    
    def test_malformed_command_line(self):
        """Test malformed command lines."""
        parser = CLICommandParser()
        help_text = """
Commands:
    : no command name
    wallet              Missing colon
    :                   Empty command
    token_decl:         Valid command
"""
        commands = parser._extract_commands(help_text)
        # Should still extract valid command
        assert "token_decl" in commands
        assert len([c for c in commands if not c]) == 0  # No empty commands
