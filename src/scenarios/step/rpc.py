"""
RPC call step executor.
"""

from typing import Any, Dict

import httpx

from ...utils.logger import get_logger
from .base import StepExecutor
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
        
        async with httpx.AsyncClient(timeout=step.timeout) as client:
            response = await client.post(url, json=payload)
            result = response.json()
        
        # Save result if requested
        if step.save:
            ctx.set_variable(step.save, result)
            logger.debug("rpc_step_saved", variable=step.save)
        
        return result

