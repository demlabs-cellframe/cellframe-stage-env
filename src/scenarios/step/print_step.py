"""Print step for outputting messages during scenario execution."""

from typing import Dict, Any
from ..schema import PrintStep
from ..executor import RuntimeContext
import structlog

logger = structlog.get_logger(__name__)


class PrintStepExecutor:
    """Executor for print steps."""
    
    def __init__(self):
        self.logger = logger
    
    async def execute(self, step: PrintStep, ctx: RuntimeContext) -> Dict[str, Any]:
        """Execute print step - output message to logs.
        
        Args:
            step: Print step to execute
            ctx: Execution context with variables
            
        Returns:
            Result dict with printed message
        """
        # Substitute variables in message
        message = ctx.substitute(step.print)
        
        # Log at specified level
        log_method = getattr(self.logger, step.level, self.logger.info)
        log_method("print_step", message=message)
        
        # Also print to console for visibility
        level_prefix = {
            "info": "ℹ️ ",
            "debug": "🔍 ",
            "warning": "⚠️ ",
            "error": "❌ "
        }.get(step.level, "")
        
        print(f"{level_prefix}{message}")
        
        return {
            "message": message,
            "level": step.level
        }

