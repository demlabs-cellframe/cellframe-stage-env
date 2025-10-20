"""
YAML scenario executor with runtime context and error handling.

Executes test scenarios step-by-step with variable substitution,
CLI command execution, and result validation.
"""

import asyncio
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils.logger import get_logger
from .parser import ScenarioParser
from .schema import (
    CLIStep, RPCStep, WaitStep, LoopStep,
    CLICheck, RPCCheck,
    TestScenario, TestStep, CheckSpec
)

logger = get_logger(__name__)


class ScenarioExecutionError(Exception):
    """Error during scenario execution."""
    
    def __init__(self, message: str, step: Optional[Any] = None, context: Optional[Dict] = None):
        self.step = step
        self.context = context
        super().__init__(self._format_message(message))
    
    def _format_message(self, message: str) -> str:
        """Format error with context."""
        parts = [message]
        if self.step:
            parts.append(f"Step: {self.step}")
        if self.context:
            parts.append(f"Context: {self.context}")
        return "\n".join(parts)


class RuntimeContext:
    """Runtime context for scenario execution."""
    
    def __init__(self, scenario: TestScenario):
        """Initialize runtime context."""
        self.scenario = scenario
        self.variables: Dict[str, Any] = scenario.variables.copy()
        self.step_results: List[Dict[str, Any]] = []
        self.start_time = time.time()
        self.parser = ScenarioParser(Path.cwd())
    
    def set_variable(self, name: str, value: Any):
        """Set runtime variable."""
        self.variables[name] = value
        logger.debug(f"Set variable: {name} = {value}")
    
    def get_variable(self, name: str) -> Any:
        """Get runtime variable."""
        if name not in self.variables:
            raise ScenarioExecutionError(f"Undefined variable: {name}")
        return self.variables[name]
    
    def substitute(self, text: str) -> str:
        """Substitute variables in text."""
        return self.parser.substitute_variables(text, self.variables)
    
    def add_result(self, step_type: str, success: bool, details: Dict[str, Any]):
        """Record step execution result."""
        result = {
            "type": step_type,
            "success": success,
            "timestamp": time.time() - self.start_time,
            **details
        }
        self.step_results.append(result)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get execution summary."""
        total = len(self.step_results)
        passed = sum(1 for r in self.step_results if r["success"])
        failed = total - passed
        duration = time.time() - self.start_time
        
        return {
            "scenario": self.scenario.name,
            "total_steps": total,
            "passed": passed,
            "failed": failed,
            "duration_seconds": round(duration, 2),
            "success_rate": round(passed / total * 100, 1) if total > 0 else 0
        }


class ScenarioExecutor:
    """Execute test scenarios with full lifecycle management."""
    
    def __init__(self, node_cli_path: str = "cellframe-node-cli"):
        """
        Initialize executor.
        
        Args:
            node_cli_path: Path to cellframe-node-cli binary
        """
        self.node_cli_path = node_cli_path
        self._running = False
    
    async def execute_scenario(self, scenario: TestScenario) -> RuntimeContext:
        """
        Execute complete test scenario.
        
        Args:
            scenario: Parsed test scenario
            
        Returns:
            Runtime context with results
            
        Raises:
            ScenarioExecutionError: If execution fails
        """
        logger.info(f"Starting scenario: {scenario.name}")
        logger.info(f"Description: {scenario.description}")
        
        ctx = RuntimeContext(scenario)
        self._running = True
        
        try:
            # Setup phase
            if scenario.setup:
                logger.info("Executing setup phase...")
                await self._execute_steps(scenario.setup, ctx)
            
            # Test phase
            logger.info("Executing test phase...")
            await self._execute_steps(scenario.test, ctx)
            
            # Check phase
            if scenario.check:
                logger.info("Executing check phase...")
                await self._execute_checks(scenario.check, ctx)
            
            summary = ctx.get_summary()
            logger.info(f"Scenario completed: {summary['passed']}/{summary['total_steps']} steps passed")
            
            if summary['failed'] > 0:
                raise ScenarioExecutionError(
                    f"Scenario failed: {summary['failed']} step(s) failed",
                    context=summary
                )
            
            return ctx
            
        except KeyboardInterrupt:
            logger.warning("Scenario execution interrupted by user")
            raise
        except ScenarioExecutionError:
            raise
        except Exception as e:
            raise ScenarioExecutionError(
                f"Unexpected error during execution: {str(e)}",
                context=ctx.get_summary()
            ) from e
        finally:
            self._running = False
    
    async def _execute_steps(self, steps: List[TestStep], ctx: RuntimeContext):
        """Execute list of test steps."""
        for i, step in enumerate(steps, 1):
            logger.info(f"Step {i}/{len(steps)}: {type(step).__name__}")
            
            if isinstance(step, CLIStep):
                await self._execute_cli_step(step, ctx)
            elif isinstance(step, RPCStep):
                await self._execute_rpc_step(step, ctx)
            elif isinstance(step, WaitStep):
                await self._execute_wait_step(step, ctx)
            elif isinstance(step, LoopStep):
                await self._execute_loop_step(step, ctx)
            else:
                raise ScenarioExecutionError(f"Unknown step type: {type(step)}")
    
    async def _execute_cli_step(self, step: CLIStep, ctx: RuntimeContext):
        """Execute CLI command step."""
        # Substitute variables in command
        cmd = ctx.substitute(step.cli)
        
        logger.debug(f"Executing CLI: {cmd} on {step.node}")
        
        try:
            # Execute command
            result = await self._run_cli_command(cmd, step.node, step.timeout)
            
            # Check expected result
            success = self._check_expectation(result, step.expect, step.contains)
            
            if not success:
                ctx.add_result("cli", False, {
                    "command": cmd,
                    "node": step.node,
                    "output": result["stdout"],
                    "error": result["stderr"],
                    "exit_code": result["returncode"]
                })
                raise ScenarioExecutionError(
                    f"CLI command failed: {cmd}\n"
                    f"Expected: {step.expect}\n"
                    f"Got: exit code {result['returncode']}"
                )
            
            # Save result to variable if requested
            if step.save:
                ctx.set_variable(step.save, result["stdout"].strip())
            
            ctx.add_result("cli", True, {
                "command": cmd,
                "node": step.node,
                "saved_to": step.save
            })
            
            # Wait if specified
            if step.wait:
                await self._wait_duration(step.wait)
                
        except subprocess.TimeoutExpired:
            ctx.add_result("cli", False, {
                "command": cmd,
                "error": f"Command timeout after {step.timeout}s"
            })
            raise ScenarioExecutionError(f"CLI command timeout: {cmd}")
    
    async def _execute_rpc_step(self, step: RPCStep, ctx: RuntimeContext):
        """Execute JSON-RPC call step."""
        # Substitute variables in method and params
        method = ctx.substitute(step.rpc)
        params = [ctx.substitute(str(p)) if isinstance(p, str) else p for p in step.params]
        
        logger.debug(f"Executing RPC: {method}({params}) on {step.node}")
        
        try:
            # Execute RPC call
            result = await self._call_rpc(method, params, step.node, step.timeout)
            
            # Check expected result
            if step.expect == "error" and "error" not in result:
                raise ScenarioExecutionError(f"Expected RPC error, got success: {method}")
            if step.expect == "success" and "error" in result:
                raise ScenarioExecutionError(f"RPC call failed: {method}\nError: {result['error']}")
            
            # Save result to variable if requested
            if step.save:
                value = result.get("result", result)
                ctx.set_variable(step.save, value)
            
            ctx.add_result("rpc", True, {
                "method": method,
                "node": step.node,
                "saved_to": step.save
            })
            
            # Wait if specified
            if step.wait:
                await self._wait_duration(step.wait)
                
        except asyncio.TimeoutError:
            ctx.add_result("rpc", False, {
                "method": method,
                "error": f"RPC timeout after {step.timeout}s"
            })
            raise ScenarioExecutionError(f"RPC call timeout: {method}")
    
    async def _execute_wait_step(self, step: WaitStep, ctx: RuntimeContext):
        """Execute wait step."""
        logger.debug(f"Waiting: {step.wait}")
        await self._wait_duration(step.wait)
        ctx.add_result("wait", True, {"duration": step.wait})
    
    async def _execute_loop_step(self, step: LoopStep, ctx: RuntimeContext):
        """Execute loop step."""
        logger.info(f"Starting loop: {step.loop} iterations")
        
        for i in range(step.loop):
            logger.debug(f"Loop iteration {i+1}/{step.loop}")
            ctx.set_variable("i", i)
            ctx.set_variable("iteration", i + 1)
            
            await self._execute_steps(step.steps, ctx)
        
        ctx.add_result("loop", True, {"iterations": step.loop})
    
    async def _execute_checks(self, checks: List[CheckSpec], ctx: RuntimeContext):
        """Execute assertion checks."""
        for i, check in enumerate(checks, 1):
            logger.info(f"Check {i}/{len(checks)}: {type(check).__name__}")
            
            if isinstance(check, CLICheck):
                await self._execute_cli_check(check, ctx)
            elif isinstance(check, RPCCheck):
                await self._execute_rpc_check(check, ctx)
            else:
                raise ScenarioExecutionError(f"Unknown check type: {type(check)}")
    
    async def _execute_cli_check(self, check: CLICheck, ctx: RuntimeContext):
        """Execute CLI assertion."""
        cmd = ctx.substitute(check.cli)
        logger.debug(f"Checking CLI: {cmd}")
        
        try:
            result = await self._run_cli_command(cmd, check.node, check.timeout)
            output = result["stdout"]
            
            # Check conditions
            if check.contains and check.contains not in output:
                raise ScenarioExecutionError(
                    f"CLI check failed: expected '{check.contains}' in output\n"
                    f"Got: {output}"
                )
            
            if check.not_contains and check.not_contains in output:
                raise ScenarioExecutionError(
                    f"CLI check failed: '{check.not_contains}' should not be in output\n"
                    f"Got: {output}"
                )
            
            if check.equals and output.strip() != check.equals:
                raise ScenarioExecutionError(
                    f"CLI check failed: expected exact match\n"
                    f"Expected: {check.equals}\n"
                    f"Got: {output}"
                )
            
            ctx.add_result("check_cli", True, {"command": cmd})
            
        except subprocess.TimeoutExpired:
            ctx.add_result("check_cli", False, {"command": cmd, "error": "timeout"})
            raise ScenarioExecutionError(f"CLI check timeout: {cmd}")
    
    async def _execute_rpc_check(self, check: RPCCheck, ctx: RuntimeContext):
        """Execute RPC assertion."""
        method = ctx.substitute(check.rpc)
        params = [ctx.substitute(str(p)) if isinstance(p, str) else p for p in check.params]
        
        logger.debug(f"Checking RPC: {method}")
        
        try:
            result = await self._call_rpc(method, params, check.node, check.timeout)
            
            if "error" in result:
                raise ScenarioExecutionError(f"RPC check failed: {method}\nError: {result['error']}")
            
            rpc_result = result.get("result")
            
            # Check conditions
            if check.result_contains is not None:
                if check.result_contains not in str(rpc_result):
                    raise ScenarioExecutionError(
                        f"RPC check failed: expected '{check.result_contains}' in result\n"
                        f"Got: {rpc_result}"
                    )
            
            if check.result_equals is not None:
                if rpc_result != check.result_equals:
                    raise ScenarioExecutionError(
                        f"RPC check failed: expected exact match\n"
                        f"Expected: {check.result_equals}\n"
                        f"Got: {rpc_result}"
                    )
            
            ctx.add_result("check_rpc", True, {"method": method})
            
        except asyncio.TimeoutError:
            ctx.add_result("check_rpc", False, {"method": method, "error": "timeout"})
            raise ScenarioExecutionError(f"RPC check timeout: {method}")
    
    async def _run_cli_command(
        self, command: str, node: str, timeout: Optional[int] = 30
    ) -> Dict[str, Any]:
        """Run CLI command via docker exec."""
        # Build docker exec command
        full_cmd = [
            "docker", "exec", node,
            self.node_cli_path, *command.split()
        ]
        
        process = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            
            return {
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace'),
                "returncode": process.returncode
            }
        except asyncio.TimeoutError:
            process.kill()
            raise
    
    async def _call_rpc(
        self, method: str, params: List[Any], node: str, timeout: Optional[int] = 30
    ) -> Dict[str, Any]:
        """Call JSON-RPC method via HTTP."""
        import httpx
        
        # Assuming RPC endpoint is at http://node:8545
        url = f"http://{node}:8545"
        
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            return response.json()
    
    async def _wait_duration(self, duration_str: str):
        """Parse and wait for duration (e.g., '5s', '100ms')."""
        match = re.match(r'(\d+)(s|ms|m)', duration_str)
        if not match:
            raise ScenarioExecutionError(f"Invalid duration format: {duration_str}")
        
        value = int(match.group(1))
        unit = match.group(2)
        
        if unit == 's':
            seconds = value
        elif unit == 'ms':
            seconds = value / 1000
        elif unit == 'm':
            seconds = value * 60
        else:
            raise ScenarioExecutionError(f"Unknown time unit: {unit}")
        
        await asyncio.sleep(seconds)
    
    def _check_expectation(
        self, result: Dict[str, Any], expect: str, contains: Optional[str]
    ) -> bool:
        """Check if result matches expectation."""
        if expect == "success":
            if result["returncode"] != 0:
                return False
        elif expect == "error":
            if result["returncode"] == 0:
                return False
        
        if contains:
            if contains not in result["stdout"]:
                return False
        
        return True

