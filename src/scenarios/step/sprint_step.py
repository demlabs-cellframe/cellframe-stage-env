"""Sprint (String Print) step for formatting and saving messages to variables."""

from typing import Dict, Any
from ..schema import SprintStep
from ..executor import RuntimeContext
import structlog

logger = structlog.get_logger(__name__)


class SprintStepExecutor:
    """Executor for sprint (string print) steps."""
    
    def __init__(self):
        self.logger = logger
    
    async def execute(self, step: SprintStep, ctx: RuntimeContext) -> Dict[str, Any]:
        """Execute sprint step - format message and save to variable.
        
        Args:
            step: Sprint step to execute
            ctx: Execution context with variables
            
        Returns:
            Result dict with formatted message
        """
        # Substitute variables in message
        message = ctx.substitute(step.sprint)
        
        # Save to variable if requested
        if step.save:
            ctx.set_variable(step.save, message)
            logger.debug("sprint_step_saved", variable=step.save, message_preview=message[:100])
        
        # Optionally print to console
        if step.print_also:
            level_prefix = {
                "info": "ℹ️ ",
                "debug": "🔍 ",
                "warning": "⚠️ ",
                "error": "❌ "
            }.get(step.level, "")
            print(f"{level_prefix}{message}")
        
        return {
            "message": message,
            "saved_to": step.save
        }

