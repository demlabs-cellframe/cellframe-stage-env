"""
SLC Executor - Core abstraction for executing SLC CLI commands.
Follows FAIL-FAST principle: no fallbacks, explicit errors.

Improvements:
- Uses centralized exception hierarchy
- Better separation of concerns
- Reusable result parser
- Type-safe command builder
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from app.core.exceptions import SLCCommandNotAllowedError, SLCExecutionError
from app.core.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SLCCommandResult:
    """
    Result of SLC command execution.
    Immutable for thread safety.
    """
    
    command: str
    exit_code: int
    stdout: str
    stderr: str
    success: bool
    parsed_json: Optional[Dict[str, Any]] = None
    
    def raise_on_error(self) -> None:
        """Raise exception if command failed. FAIL-FAST."""
        if not self.success:
            raise SLCExecutionError(
                f"SLC command failed: {self.command}",
                details={
                    "exit_code": self.exit_code,
                    "stderr": self.stderr,
                    "stdout": self.stdout[:500]  # Truncate for readability
                }
            )
    
    def get_json_or_fail(self) -> Dict[str, Any]:
        """Get parsed JSON or raise error. FAIL-FAST."""
        if self.parsed_json is None:
            raise SLCExecutionError(
                f"Command did not return JSON: {self.command}",
                details={"stdout": self.stdout[:500]}
            )
        return self.parsed_json


class CommandWhitelist:
    """
    Centralized command whitelist management.
    Single Responsibility: manage allowed commands.
    """
    
    # Core SLC commands that are safe to expose via API
    ALLOWED_COMMANDS: Set[str] = {
        # Task management
        "list", "create",
        
        # Context management
        "update-context", "load-context", "reload-context", "analyze-context",
        
        # Template management
        "templates", "search", "info", "recommend", "intelligent-recommend",
        "tpl-create",
        
        # System commands
        "status", "validate", "optimize", "help",
        
        # Organization
        "organize", "cleanup", "org-stats", "monitor",
        
        # Intelligence & Analytics
        "intelligence-stats", "template-evolution", "record-usage",
        "generate-adaptive",
        
        # Evolution system
        "export", "import", "evolution-validate", "create-archive",
        
        # Reflection
        "reflection"
    }
    
    @classmethod
    def is_allowed(cls, command: str) -> bool:
        """Check if command is in whitelist."""
        return command in cls.ALLOWED_COMMANDS
    
    @classmethod
    def validate_or_raise(cls, command: str) -> None:
        """Validate command or raise exception. FAIL-FAST."""
        if not cls.is_allowed(command):
            raise SLCCommandNotAllowedError(
                command=command,
                allowed_commands=sorted(cls.ALLOWED_COMMANDS)
            )


class JSONParser:
    """
    Reusable JSON parser with error handling.
    Single Responsibility: parse command output.
    """
    
    @staticmethod
    def parse(text: str, command: str) -> Optional[Dict[str, Any]]:
        """
        Parse JSON from text, return None if invalid.
        
        Args:
            text: Text to parse
            command: Command name (for logging)
        
        Returns:
            Parsed JSON dict or None
        """
        if not text.strip():
            return None
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(
                "failed_to_parse_json",
                command=command,
                error=str(e),
                text_preview=text[:200]
            )
            return None


class CommandExecutor:
    """
    Low-level command executor.
    Single Responsibility: execute subprocess commands.
    """
    
    @staticmethod
    async def execute(
        command_parts: List[str],
        cwd: Path,
        timeout: Optional[float] = 30.0
    ) -> tuple[int, str, str]:
        """
        Execute command asynchronously.
        
        Args:
            command_parts: Command and arguments as list
            cwd: Working directory
            timeout: Timeout in seconds
        
        Returns:
            Tuple of (exit_code, stdout, stderr)
        
        Raises:
            asyncio.TimeoutError: If command times out
            SLCExecutionError: If command execution fails
        """
        try:
            process = await asyncio.create_subprocess_exec(
                *command_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd)
            )
            
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = process.returncode or 0
            
            return exit_code, stdout, stderr
            
        except asyncio.TimeoutError:
            logger.error(
                "command_timeout",
                command=" ".join(command_parts),
                timeout=timeout
            )
            raise
        
        except Exception as e:
            logger.exception(
                "command_execution_failed",
                command=" ".join(command_parts),
                error=str(e)
            )
            raise SLCExecutionError(
                f"Failed to execute command: {' '.join(command_parts)}",
                details={"error": str(e)}
            ) from e


class SLCExecutor:
    """
    High-level SLC CLI executor.
    
    Design principles:
    - FAIL-FAST: No fallbacks, explicit errors
    - Real execution: No mocks or stubs
    - Type-safe: Proper typing and validation
    - Async-first: All commands run async
    - DRY: Delegates to specialized components
    """
    
    def __init__(self, cli_path: Path, project_root: Path) -> None:
        """
        Initialize SLC executor.
        
        Args:
            cli_path: Path to SLC CLI executable
            project_root: Path to project root (working directory for commands)
        
        Raises:
            ValueError: If paths don't exist (FAIL-FAST)
        """
        if not cli_path.exists():
            raise ValueError(f"SLC CLI not found: {cli_path}")
        
        if not project_root.exists():
            raise ValueError(f"Project root not found: {project_root}")
        
        self.cli_path = cli_path
        self.project_root = project_root
        self.whitelist = CommandWhitelist()
        self.json_parser = JSONParser()
        self.executor = CommandExecutor()
        
        logger.info(
            "slc_executor_initialized",
            cli_path=str(cli_path),
            project_root=str(project_root),
            allowed_commands=len(CommandWhitelist.ALLOWED_COMMANDS)
        )
    
    async def execute(
        self,
        command: str,
        args: Optional[List[str]] = None,
        parse_json: bool = True,
        timeout: Optional[float] = 30.0
    ) -> SLCCommandResult:
        """
        Execute SLC command asynchronously.
        
        Args:
            command: SLC command name (e.g., "list", "update-context")
            args: Optional command arguments
            parse_json: Try to parse stdout as JSON (for commands with JSON output)
            timeout: Command timeout in seconds (None = no timeout)
        
        Returns:
            SLCCommandResult with execution details
        
        Raises:
            SLCCommandNotAllowedError: If command not in whitelist
            SLCExecutionError: If command execution fails critically
            asyncio.TimeoutError: If command times out
        """
        # Validate command is allowed
        self.whitelist.validate_or_raise(command)
        
        # Build command parts
        command_parts = [str(self.cli_path), command]
        if args:
            command_parts.extend(args)
        
        cmd_str = " ".join(command_parts)
        
        logger.info(
            "executing_slc_command",
            command=command,
            args=args,
            full_command=cmd_str
        )
        
        # Execute command
        exit_code, stdout, stderr = await self.executor.execute(
            command_parts=command_parts,
            cwd=self.project_root,
            timeout=timeout
        )
        
        success = exit_code == 0
        
        # Parse JSON if requested
        parsed_json = None
        if parse_json and success and stdout.strip():
            parsed_json = self.json_parser.parse(stdout, command)
        
        # Create result
        result = SLCCommandResult(
            command=cmd_str,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            success=success,
            parsed_json=parsed_json
        )
        
        # Log result
        if success:
            logger.info(
                "slc_command_success",
                command=command,
                exit_code=exit_code,
                has_json=parsed_json is not None
            )
        else:
            logger.error(
                "slc_command_failed",
                command=command,
                exit_code=exit_code,
                stderr=stderr[:500]
            )
        
        return result
    
    async def execute_with_json(
        self,
        command: str,
        args: Optional[List[str]] = None,
        timeout: Optional[float] = 30.0
    ) -> Dict[str, Any]:
        """
        Execute command and return JSON result or raise error.
        Convenience method for commands that always return JSON.
        
        Args:
            command: SLC command name
            args: Optional command arguments
            timeout: Command timeout in seconds
        
        Returns:
            Parsed JSON result
        
        Raises:
            SLCExecutionError: If command fails or doesn't return JSON
        """
        result = await self.execute(command, args, parse_json=True, timeout=timeout)
        result.raise_on_error()
        return result.get_json_or_fail()
