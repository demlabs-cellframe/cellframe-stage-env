"""Unit tests for CLI parser."""

import pytest
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from src.utils.cli_parser import CLICommandParser


class TestCLICommandParser:
    """Test CLI command parser functionality."""
    
    def test_extract_commands_from_main_help(self, cli_help_main):
        """Test extracting command list from main help output."""
        parser = CLICommandParser()
        commands = parser._extract_commands(cli_help_main)
        
        assert len(commands) > 0, "Should extract commands"
        assert "token_decl" in commands
        assert "token_emit" in commands
        assert "wallet" in commands
        assert "tx_create" in commands
        
        # Filter out help keywords
        assert "help" not in commands
        assert "exit" not in commands
        assert "version" not in commands
    
    def test_extract_options_from_command_help(self, cli_help_token_decl):
        """Test extracting options from command-specific help."""
        parser = CLICommandParser()
        options = parser._extract_options(cli_help_token_decl)
        
        assert len(options) > 0, "Should extract options"
        assert "net" in options
        assert "chain" in options
        assert "token" in options
        assert "total_supply" in options
        assert "signs_total" in options
        assert "certs" in options
        assert "flags" in options
        assert "decimals" in options
    
    def test_apply_cli_defaults_adds_missing_option(self):
        """Test that defaults are added to commands missing options."""
        parser = CLICommandParser()
        
        # Manually set commands for testing
        parser.commands = {
            "token_decl": {"net", "token", "total_supply", "certs"}
        }
        parser._parsed = True
        
        cmd = "token_decl -token TEST -total_supply 1000000"
        defaults = {"net": "stagenet"}
        
        result = parser.apply_cli_defaults(cmd, defaults)
        
        assert "-net stagenet" in result
        assert result.startswith("token_decl")
    
    def test_apply_cli_defaults_doesnt_duplicate(self):
        """Test that existing options are not duplicated."""
        parser = CLICommandParser()
        
        parser.commands = {
            "token_decl": {"net", "token"}
        }
        parser._parsed = True
        
        cmd = "token_decl -net stagenet -token TEST"
        defaults = {"net": "mainnet"}  # Try to override
        
        result = parser.apply_cli_defaults(cmd, defaults)
        
        # Should NOT add -net again
        assert result == cmd
        assert result.count("-net") == 1
    
    def test_apply_cli_defaults_ignores_unsupported_options(self):
        """Test that unsupported options are skipped when available_options is populated."""
        parser = CLICommandParser()
        
        parser.commands = {
            "token_decl": {"net", "token"}  # Only net and token supported
        }
        parser._parsed = True
        
        cmd = "token_decl -token TEST"
        defaults = {
            "net": "stagenet",
            "unsupported_option": "value"  # Not in command options
        }
        
        result = parser.apply_cli_defaults(cmd, defaults)
        
        assert "-net stagenet" in result
        assert "-unsupported_option" not in result
    
    def test_apply_cli_defaults_adds_all_when_unparsed(self):
        """Test that all defaults are added when parser has no options for the command."""
        parser = CLICommandParser()
        
        parser.commands = {}
        parser._parsed = True
        
        cmd = "some_cmd -token TEST"
        defaults = {
            "net": "stagenet",
            "chain": "zerochain",
        }
        
        result = parser.apply_cli_defaults(cmd, defaults)
        
        assert "-net stagenet" in result
        assert "-chain zerochain" in result
    
    def test_load_from_empty_cache_returns_false(self, tmp_path):
        """Test that empty cache is rejected."""
        import json
        
        cache_file = tmp_path / "empty_cache.json"
        cache_file.write_text("{}")
        
        parser = CLICommandParser(cache_file=cache_file)
        result = parser.load_from_cache()
        
        assert result is False, "Empty cache should be rejected"
        assert parser._parsed is False
    
    def test_load_from_valid_cache_returns_true(self, tmp_path):
        """Test that valid cache is loaded."""
        import json
        
        cache_file = tmp_path / "valid_cache.json"
        cache_data = {
            "token_decl": ["net", "token", "total_supply"],
            "wallet": ["net", "name"]
        }
        cache_file.write_text(json.dumps(cache_data))
        
        parser = CLICommandParser(cache_file=cache_file)
        result = parser.load_from_cache()
        
        assert result is True, "Valid cache should be loaded"
        assert parser._parsed is True
        assert len(parser.commands) == 2
        assert "token_decl" in parser.commands
        assert "net" in parser.commands["token_decl"]
    
    def test_save_to_cache(self, tmp_path):
        """Test saving parsed commands to cache."""
        import json
        
        cache_file = tmp_path / "test_cache.json"
        
        parser = CLICommandParser(cache_file=cache_file)
        parser.commands = {
            "token_decl": {"net", "token"},
            "wallet": {"net", "name"}
        }
        parser._parsed = True
        
        result = parser.save_to_cache()
        
        assert result is True
        assert cache_file.exists()
        
        # Verify cache content
        cached_data = json.loads(cache_file.read_text())
        assert "token_decl" in cached_data
        assert "net" in cached_data["token_decl"]
    
    def test_apply_cli_defaults_for_net_command(self):
        """Test that defaults are applied to 'net' command with subcommands."""
        parser = CLICommandParser()
        
        # Manually set commands for testing
        # 'net' command supports -net option
        parser.commands = {
            "net": {"net"}  # net command supports -net option
        }
        parser._parsed = True
        
        # Test case: "net go offline" should get -net added
        cmd = "net go offline"
        defaults = {"net": "stagenet"}
        
        result = parser.apply_cli_defaults(cmd, defaults)
        
        # Should add -net stagenet
        assert "-net stagenet" in result, f"Expected -net stagenet in result, got: {result}"
        assert result.startswith("net go offline"), f"Command should start with 'net go offline', got: {result}"
    
    def test_apply_cli_defaults_for_net_go_online(self):
        """Test that defaults are applied to 'net go online' command."""
        parser = CLICommandParser()
        
        parser.commands = {
            "net": {"net"}  # net command supports -net option
        }
        parser._parsed = True
        
        cmd = "net go online"
        defaults = {"net": "stagenet"}
        
        result = parser.apply_cli_defaults(cmd, defaults)
        
        assert "-net stagenet" in result, f"Expected -net stagenet in result, got: {result}"
    
    def test_apply_cli_defaults_for_node_dump(self):
        """Test that defaults are applied to 'node dump' command."""
        parser = CLICommandParser()
        
        parser.commands = {
            "node": {"net"}  # node command supports -net option
        }
        parser._parsed = True
        
        cmd = "node dump"
        defaults = {"net": "stagenet"}
        
        result = parser.apply_cli_defaults(cmd, defaults)
        
        assert "-net stagenet" in result, f"Expected -net stagenet in result, got: {result}"
    
    def test_apply_cli_defaults_for_node_add(self):
        """Test that defaults are applied to 'node add' command."""
        parser = CLICommandParser()
        
        parser.commands = {
            "node": {"net"}  # node command supports -net option
        }
        parser._parsed = True
        
        cmd = "node add -addr 1234::5678"
        defaults = {"net": "stagenet"}
        
        result = parser.apply_cli_defaults(cmd, defaults)
        
        assert "-net stagenet" in result, f"Expected -net stagenet in result, got: {result}"
        assert "-addr 1234::5678" in result, "Original -addr should be preserved"

