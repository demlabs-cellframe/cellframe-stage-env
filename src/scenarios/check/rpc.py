"""
RPC check executor.
"""

import asyncio
import httpx

from ...utils.logger import get_logger
from .base import CheckExecutor
from ..schema import RPCCheck
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class RPCCheckExecutor(CheckExecutor):
    """Executor for RPC checks."""
    
    async def execute(self, check: RPCCheck, ctx: RuntimeContext) -> None:
        """Execute RPC check."""
        method = ctx.substitute(check.rpc)
        params = [ctx.substitute(str(p)) if isinstance(p, str) else p for p in check.params]
        
        logger.debug(f"Checking RPC: {method}")
        
        try:
            # Build RPC URL
            node = ctx.substitute(check.node) if check.node else "node1"
            url = f"http://{node}:8545"
            
            payload = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": 1
            }
            
            async with httpx.AsyncClient(timeout=check.timeout) as client:
                response = await client.post(url, json=payload)
                result = response.json()
            
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

