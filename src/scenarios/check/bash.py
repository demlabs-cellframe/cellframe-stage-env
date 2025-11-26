"""
Bash check executor.
"""

from ...utils.logger import get_logger
from .base import CheckExecutor
from ..schema import BashCheck
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class BashCheckExecutor(CheckExecutor):
    """Executor for Bash checks."""
    
    async def execute(self, check: BashCheck, ctx: RuntimeContext) -> None:
        """Execute Bash check."""
        script = ctx.substitute(check.bash)
        logger.debug(f"Checking Bash: {script[:50]}...")
        
        try:
            result = await self.container_manager.exec_bash_command(
                script=script,
                node=check.node,
                timeout=check.timeout
            )
            
            if result["returncode"] != 0:
                ctx.add_result("check_bash", False, {
                    "error": f"Exit code {result['returncode']}",
                    "stdout": result["stdout"],
                    "stderr": result["stderr"]
                })
                raise ScenarioExecutionError(
                    f"Bash check failed: exit code {result['returncode']}\n"
                    f"stdout: {result['stdout']}\n"
                    f"stderr: {result['stderr']}"
                )
            
            ctx.add_result("check_bash", True, {"script": script[:50]})
            
        except Exception as e:
            ctx.add_result("check_bash", False, {"error": str(e)})
            raise ScenarioExecutionError(f"Bash check error: {str(e)}")

