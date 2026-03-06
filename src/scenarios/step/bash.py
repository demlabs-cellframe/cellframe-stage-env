"""
Bash script step executor.
"""

import asyncio
from typing import Any, Dict

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import BashStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class BashStepExecutor(StepExecutor):
    """Executor for Bash script steps."""
    
    async def execute(self, step: BashStep, ctx: RuntimeContext) -> Dict[str, Any]:
        """Execute Bash script step."""
        # Substitute variables in bash script
        script = ctx.substitute(step.bash)
        
        # If node is specified, execute in container; otherwise execute on host
        timeout = step.timeout or 300
        if step.node:
            node = ctx.substitute(step.node)
            result = await self.container_manager.exec_bash_command(
                script=script,
                node=node,
                timeout=timeout
            )
        else:
            logger.info("executing_bash_on_host", script_preview=script[:100])
            result = await self._exec_on_host(script, timeout)
        
        # Save result if requested
        if step.save:
            var_name = ctx.substitute(step.save)
            ctx.set_variable(var_name, result["stdout"])
            logger.info("bash_step_saved", variable=var_name,
                        save_template=step.save,
                        stdout_len=len(result["stdout"]))
        
        # Check expectation
        if step.expect == "success" and result["returncode"] != 0:
            raise ScenarioExecutionError(
                f"Bash step failed: Expected success but got exit code {result['returncode']}",
                step=script[:100],
                context=result
            )
        elif step.expect == "error" and result["returncode"] == 0:
            raise ScenarioExecutionError(
                f"Bash step failed: Expected error but got success",
                step=script[:100],
                context=result
            )
        
        return result
    
    async def _exec_on_host(self, script: str, timeout: int = 300) -> Dict[str, Any]:
        """Execute bash script on host machine (not in container)."""
        process = await asyncio.create_subprocess_shell(
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            shell=True
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            
            result = {
                "stdout": stdout.decode('utf-8', errors='replace'),
                "stderr": stderr.decode('utf-8', errors='replace'),
                "returncode": process.returncode
            }
            
            logger.info("bash_host_execution_completed",
                       returncode=result["returncode"],
                       stdout_preview=result["stdout"][:200] if result["stdout"] else "")
            
            return result
        except asyncio.TimeoutError:
            process.kill()
            logger.error("bash_host_execution_timeout", timeout=timeout)
            raise

