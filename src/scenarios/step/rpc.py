"""
RPC call step executor.
"""

from typing import Any, Dict

import httpx

from ...utils.logger import get_logger
from .base import StepExecutor, resolve_timeout
from ..schema import RPCStep
from ..executor import RuntimeContext

logger = get_logger(__name__)


class RPCStepExecutor(StepExecutor):
    """Executor for RPC call steps."""
    
    async def execute(self, step: RPCStep, ctx: RuntimeContext) -> Dict[str, Any]:
        """Execute RPC call step."""
        # Substitute variables
        method = ctx.substitute(step.rpc)
        params = [ctx.substitute(p) if isinstance(p, str) else p for p in step.params] if step.params else []
        node = ctx.substitute(step.node) if step.node else "node1"
        
        # Build RPC URL
        url = f"http://{node}:8545"
        
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": 1
        }
        
        timeout = resolve_timeout(step.timeout, ctx, default=30)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            result = response.json()
        
        if step.save or step.save_map:
            output = str(result) if not isinstance(result, str) else result
            ctx.save_output(output, step.save, step.save_regex, step.save_map)
        
        return result

