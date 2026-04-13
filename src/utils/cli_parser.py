"""
CLI command parser for extracting available options from help output.

Parses cellframe-node-cli help to build a map of commands and their options,
enabling automatic prefix injection in scenarios.
"""

import re
import json
from typing import Dict, List, Set
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Bump when cache format or extraction logic changes so stale/broken caches are ignored.
_CLI_CACHE_VERSION = 2

# If cached command map looks like a failed parse (e.g. only "output"/"Total"), reload from container.
_MIN_SANE_COMMAND_COUNT = 8
_SENTINEL_COMMANDS = frozenset(
    {"help", "token", "wallet", "mempool", "net", "node", "version"}
)


class CLICommandParser:
    """Parse CLI commands and extract available options."""
    
    def __init__(self, cache_file: Path = None):
        """
        Initialize CLI parser.
        
        Args:
            cache_file: Optional path to cache file for parsed commands
        """
        self.commands: Dict[str, Set[str]] = {}
        self._parsed = False
        self.cache_file = cache_file
        self._warned_commands: Set[str] = set()
    
    def load_from_cache(self) -> bool:
        """
        Load parsed commands from cache file.
        
        Returns:
            True if cache was loaded successfully
        """
        if not self.cache_file or not self.cache_file.exists():
            return False
        
        try:
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
            
            if isinstance(data, dict) and "_meta" in data:
                meta = data.get("_meta") or {}
                if meta.get("version") != _CLI_CACHE_VERSION:
                    logger.warning(
                        "CLI command cache version mismatch - will reparse",
                        cached=meta.get("version"),
                        expected=_CLI_CACHE_VERSION,
                    )
                    return False
                payload = {k: v for k, v in data.items() if k != "_meta"}
            else:
                payload = data
            
            # Convert lists back to sets
            self.commands = {
                cmd: set(opts) 
                for cmd, opts in payload.items()
            }
            
            # Validate cache is not empty
            if not self.commands:
                logger.warning("Cache file exists but is empty - will reparse")
                return False
            
            keys = set(self.commands.keys())
            if len(keys) < _MIN_SANE_COMMAND_COUNT or not (keys & _SENTINEL_COMMANDS):
                logger.warning(
                    "CLI command cache looks corrupt (too few or wrong command names) - will reparse",
                    command_count=len(keys),
                    sample=list(keys)[:12],
                )
                return False
            
            self._parsed = True
            logger.info(f"Loaded CLI commands from cache: {len(self.commands)} commands")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
            return False
    
    def save_to_cache(self) -> bool:
        """
        Save parsed commands to cache file.
        
        Returns:
            True if cache was saved successfully
        """
        if not self.cache_file or not self._parsed:
            return False
        
        try:
            # Ensure cache directory exists
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert sets to lists for JSON serialization
            data = {
                cmd: list(opts) 
                for cmd, opts in self.commands.items()
            }
            data["_meta"] = {"version": _CLI_CACHE_VERSION}
            
            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.info(f"Saved CLI commands to cache: {self.cache_file}")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")
            return False
    
    async def parse_cli_help(self, node_container: str, use_cache: bool = True) -> bool:
        """
        Parse CLI help from a running node container.
        
        Args:
            node_container: Docker container name
            use_cache: If True, try to load from cache first
            
        Returns:
            True if parsing succeeded
        """
        import asyncio
        
        # Try cache first
        if use_cache and self.load_from_cache():
            return True
        
        try:
            logger.info("Parsing CLI help from container", container=node_container)
            
            # Get main help (use "help" command to list all commands)
            main_help = await self._exec_cli_help(node_container, ["help"])
            if not main_help:
                logger.warning("Failed to get main CLI help")
                return False
            
            # Log help output for debugging
            logger.info(f"CLI help output (first 500 chars): {main_help[:500]}")
            
            help_text = self._normalize_help_text(main_help)
            # Extract command list from main help
            commands = self._extract_commands(help_text)
            logger.info(f"Found {len(commands)} CLI commands")
            
            if len(commands) == 0:
                logger.warning(f"No commands extracted from help. Help output length: {len(main_help)}")
                logger.warning(f"Full help output: {repr(main_help)}")
            
            # Parse help for each command
            for cmd in commands:
                # Cellframe CLI format: "help <command>" not "<command> -h"
                cmd_help = await self._exec_cli_help(node_container, ["help", cmd])
                if cmd_help:
                    cmd_help = self._normalize_help_text(cmd_help)
                    options = self._extract_options(cmd_help)
                    self.commands[cmd] = options
                    logger.debug(f"Command '{cmd}': {len(options)} options")
            
            self._parsed = True
            logger.info(f"CLI parsing complete: {len(self.commands)} commands mapped")
            
            # Save to cache
            self.save_to_cache()
            
            return True
            
        except Exception as e:
            logger.error("Failed to parse CLI help", error=str(e))
            return False
    
    async def _exec_cli_help(self, container: str, args: List[str]) -> str:
        """Execute CLI help command in container."""
        import asyncio
        
        cmd = ["docker", "exec", container, "cellframe-node-cli"] + args
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            
            if proc.returncode == 0:
                return stdout.decode('utf-8', errors='ignore')
            else:
                # Some commands return help on stderr with non-zero exit
                return stderr.decode('utf-8', errors='ignore')
                
        except asyncio.TimeoutError:
            logger.warning("CLI help command timeout", args=args)
            return ""
        except Exception as e:
            logger.debug("CLI help exec failed", args=args, error=str(e))
            return ""
    
    def _normalize_help_text(self, raw: str) -> str:
        """Turn JSON-RPC / human-readable CLI help into plain text for parsing."""
        text = raw.strip()
        if not text:
            return ""
        # Raw JSON from CLI (non-pretty path): [{"output":"..."}] or {"output":"..."}
        if text.startswith(("[", "{")):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list) and parsed:
                    parsed = parsed[0]
                if isinstance(parsed, dict) and "output" in parsed:
                    inner = parsed.get("output")
                    if isinstance(inner, str):
                        return inner
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        # Human text from s_json_str_to_text: "output: <text>"
        if text.startswith("output:"):
            rest = text[len("output:") :].lstrip()
            return rest
        return text

    def _extract_commands_from_table(self, help_text: str) -> List[str]:
        """Extract command names from 6.x table help ( 'cmd  | desc |' )."""
        seen: Set[str] = set()
        commands: List[str] = []
        skip = {
            "command",
            "description",
            "output",
            "total",
            "exit",
            "quit",
            "?",
            "commands",
            "usage",
            "options",
        }

        for line in help_text.split("\n"):
            if "|" not in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue
            name = parts[0].strip()
            if not name:
                continue
            if name.lower().startswith("total") or "total commands" in line.lower():
                continue
            if set(name) <= {"_", "-", " "} or "___" in name:
                continue
            if name.lower() in skip:
                continue
            # First column is fixed-width; may contain spaces for single-token commands
            name = " ".join(name.split())
            if not name or name in seen:
                continue
            seen.add(name)
            commands.append(name)
        return commands

    def _extract_commands(self, help_text: str) -> List[str]:
        """Extract command names from main help output."""
        # Prefer table format (6.x+)
        table_cmds = self._extract_commands_from_table(help_text)
        if len(table_cmds) >= _MIN_SANE_COMMAND_COUNT and any(
            c in _SENTINEL_COMMANDS for c in table_cmds
        ):
            return table_cmds

        seen: Set[str] = set()
        commands: List[str] = []
        skip = {'help', 'version', 'exit', 'quit', '?', 'Commands', 'Usage', 'Options'}

        for line in help_text.split('\n'):
            # Format 1: "command_name:\t\t\tDescription" (single-word command)
            match = re.match(r'^\s*([a-zA-Z_][a-zA-Z0-9_]*):\s+', line)
            if match:
                cmd = match.group(1)
                if cmd not in skip and cmd not in seen:
                    seen.add(cmd)
                    commands.append(cmd)
                continue
            # Format 2: "node dump:\t\t\tDescription" (6.x: parent + subcommand) -> add "node"
            match2 = re.match(r'^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+[a-zA-Z_][a-zA-Z0-9_]*\s*:', line)
            if match2:
                parent = match2.group(1)
                if parent not in skip and parent not in seen:
                    seen.add(parent)
                    commands.append(parent)
        return commands
    
    def _extract_options(self, help_text: str) -> Set[str]:
        """Extract option names from command help output."""
        options = set()
        
        # Cellframe CLI format: -net <net_name> or [-chain <chain_name>]
        # Extract all -option patterns
        
        # Pattern 1: -option <value> or -option [value]
        pattern = r'-([a-zA-Z_]\w+)\s+[<\[]'
        for match in re.finditer(pattern, help_text):
            option = match.group(1)
            options.add(option)
        
        # Pattern 2: -flag (standalone flags without values)
        # Look for -flag in description lines
        flag_pattern = r'\s-([a-zA-Z_]\w+)(?:\s|$|,)'
        for match in re.finditer(flag_pattern, help_text):
            option = match.group(1)
            # Skip very short (likely not real options)
            if len(option) > 1:
                options.add(option)
        
        return options
    
    def get_command_options(self, command: str) -> Set[str]:
        """
        Get available options for a command.
        
        Args:
            command: Command name (e.g., 'token_decl')
            
        Returns:
            Set of option names (e.g., {'net', 'token', 'total_supply'})
        """
        return self.commands.get(command, set())
    
    def has_option(self, command: str, option: str) -> bool:
        """
        Check if command supports an option.
        
        Args:
            command: Command name
            option: Option name (without -)
            
        Returns:
            True if command has this option
        """
        return option in self.get_command_options(command)
    
    def apply_cli_defaults(self, cli_command: str, defaults: Dict[str, str]) -> str:
        """
        Apply default option values to CLI command.
        
        Args:
            cli_command: Original CLI command string
            defaults: Dict of option:value pairs (e.g., {'net': 'stagenet'})
            
        Returns:
            CLI command with defaults applied
        """
        if not defaults:
            return cli_command
        
        # "net list" in 6.x takes no arguments; adding -net causes "To many arguments"
        if isinstance(cli_command, str) and cli_command.strip().startswith("net list"):
            return cli_command
        
        # Ensure cli_command is a string
        if not isinstance(cli_command, str):
            logger.warning(f"apply_cli_defaults received non-string command: {type(cli_command)}")
            return str(cli_command) if cli_command else ""
        
        # Extract command name (first word)
        parts = cli_command.split()
        if not parts:
            return cli_command
        
        command = parts[0]
        
        # Get available options for this command (may be empty if help parsing found no options)
        available_options = self.get_command_options(command)
        command_known = command in self.commands

        # Debug logging
        logger.debug(f"apply_cli_defaults: cli_command='{cli_command}', command='{command}', available_options={available_options}, defaults={defaults}, parsed={self._parsed}")

        if not command_known and command not in self._warned_commands:
            self._warned_commands.add(command)
            if self._parsed:
                logger.debug(
                    f"Command '{command}' not in parsed help output (may be unlisted/plugin command)"
                )
            else:
                logger.warning(
                    f"CLI parser not initialized. Cannot apply defaults for command '{command}'."
                )
        
        # Build list of options to add
        options_to_add = []
        for option, value in defaults.items():
            import re
            pattern = rf'(^|\s)-{re.escape(option)}(\s|$)'
            if re.search(pattern, cli_command):
                continue
            if not self._parsed or not command_known:
                options_to_add.append(f"-{option} {value}")
                logger.debug(f"Permissively adding -{option} {value} to command '{cli_command}' (parsed={self._parsed}, command_known={command_known})")
            elif option in available_options:
                options_to_add.append(f"-{option} {value}")
                logger.debug(f"Adding option -{option} {value} to command '{cli_command}'")
            else:
                logger.debug(f"Option '{option}' not in available_options {available_options} for command '{command}'")
        
        # Add options to command
        # FIX: Insert defaults after command name, not at the end
        # This avoids CLI parser bugs when defaults are appended after user parameters
        if options_to_add:
            # Append defaults to the end of the command
            # This works correctly for both simple commands and commands with subcommands
            # Examples:
            # - "wallet new" -> "wallet new -net stagenet"
            # - "node dump" -> "node dump -net stagenet"
            result = f"{cli_command} {' '.join(options_to_add)}"
            logger.debug(f"apply_cli_defaults result: '{result}'")
            return result
        
        logger.debug(f"apply_cli_defaults: no options added, returning original: '{cli_command}'")
        return cli_command
    
    def get_stats(self) -> Dict:
        """Get parsing statistics."""
        return {
            "parsed": self._parsed,
            "total_commands": len(self.commands),
            "commands": {
                cmd: len(opts) 
                for cmd, opts in self.commands.items()
            }
        }


# Global singleton instance
_cli_parser: CLICommandParser = None


def get_cli_parser(cache_file: Path = None) -> CLICommandParser:
    """
    Get global CLI parser instance.
    
    Args:
        cache_file: Optional cache file path (only used on first call)
    
    Returns:
        Global CLICommandParser instance
    """
    global _cli_parser
    if _cli_parser is None:
        _cli_parser = CLICommandParser(cache_file=cache_file)
        # Try to load from cache if cache_file is provided
        if cache_file:
            _cli_parser.load_from_cache()
        else:
            # Try default cache location
            from pathlib import Path
            default_cache = Path(__file__).parent.parent.parent / ".cache" / "cli_commands.json"
            if default_cache.exists():
                _cli_parser.cache_file = default_cache
                _cli_parser.load_from_cache()
    return _cli_parser

