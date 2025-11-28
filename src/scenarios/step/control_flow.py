"""
Control flow step executors (If, While, Switch, Set).
"""

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import SetStep, IfStep, WhileStep, SwitchStep, ForStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class SetStepExecutor(StepExecutor):
    """Executor for variable assignment."""
    
    async def execute(self, step: SetStep, ctx: RuntimeContext) -> None:
        """Execute set step."""
        var_name = step.set
        
        if step.eval:
            # Evaluate expression using context variables
            expr = str(step.value)
            try:
                # Use context variables as locals for evaluation
                value = eval(expr, {"__builtins__": __builtins__}, ctx.variables)
            except Exception as e:
                raise ScenarioExecutionError(f"Failed to evaluate expression '{expr}': {e}", step=step)
        else:
            # Literal value (substitute variables if string)
            value = step.value
            if isinstance(value, str):
                value = ctx.substitute(value)
                
        ctx.set_variable(var_name, value)
        logger.info(f"Set variable '{var_name}' = {value}")
        ctx.add_result("set", True, {"variable": var_name, "value": str(value)})


class IfStepExecutor(StepExecutor):
    """Executor for conditional logic."""
    
    def __init__(self, container_manager, log_file=None, debug=False, execute_steps_callback=None):
        super().__init__(container_manager, log_file, debug)
        self.execute_steps_callback = execute_steps_callback
        
    async def execute(self, step: IfStep, ctx: RuntimeContext, defaults=None) -> None:
        """Execute if step."""
        if not self.execute_steps_callback:
            raise RuntimeError("execute_steps_callback not set for IfStepExecutor")
            
        condition = step.condition
        try:
            # Evaluate condition
            result = eval(condition, {"__builtins__": __builtins__}, ctx.variables)
            logger.info(f"Condition '{condition}' evaluated to: {result}")
        except Exception as e:
            raise ScenarioExecutionError(f"Failed to evaluate condition '{condition}': {e}", step=step)
            
        if result:
            logger.info("Condition is TRUE, executing 'then' steps")
            await self.execute_steps_callback(step.then_steps, ctx, defaults)
        elif step.else_steps:
            logger.info("Condition is FALSE, executing 'else' steps")
            await self.execute_steps_callback(step.else_steps, ctx, defaults)
        else:
            logger.info("Condition is FALSE, no 'else' steps")
            
        ctx.add_result("if", True, {"condition": condition, "result": bool(result)})


class WhileStepExecutor(StepExecutor):
    """Executor for while loop."""
    
    def __init__(self, container_manager, log_file=None, debug=False, execute_steps_callback=None):
        super().__init__(container_manager, log_file, debug)
        self.execute_steps_callback = execute_steps_callback
        
    async def execute(self, step: WhileStep, ctx: RuntimeContext, defaults=None) -> None:
        """Execute while step."""
        if not self.execute_steps_callback:
            raise RuntimeError("execute_steps_callback not set for WhileStepExecutor")
            
        condition = step.condition
        max_loops = step.max_loops
        loops = 0
        
        logger.info(f"Starting while loop: '{condition}' (max {max_loops})")
        
        while loops < max_loops:
            try:
                result = eval(condition, {"__builtins__": __builtins__}, ctx.variables)
            except Exception as e:
                raise ScenarioExecutionError(f"Failed to evaluate condition '{condition}': {e}", step=step)
                
            if not result:
                logger.info(f"While loop ended: condition false after {loops} iterations")
                break
                
            logger.info(f"While loop iteration {loops+1}/{max_loops}")
            await self.execute_steps_callback(step.steps, ctx, defaults)
            loops += 1
            
        if loops >= max_loops:
            logger.warning(f"While loop terminated due to max_loops limit ({max_loops})")
            
        ctx.add_result("while", True, {"condition": condition, "loops": loops})


class ForStepExecutor(StepExecutor):
    """Executor for for loop."""
    
    def __init__(self, container_manager, log_file=None, debug=False, execute_steps_callback=None):
        super().__init__(container_manager, log_file, debug)
        self.execute_steps_callback = execute_steps_callback
        
    async def execute(self, step: ForStep, ctx: RuntimeContext, defaults=None) -> None:
        """Execute for step."""
        if not self.execute_steps_callback:
            raise RuntimeError("execute_steps_callback not set for ForStepExecutor")
            
        item_var = step.item_var
        in_items = step.in_items
        
        # Determine items list
        items = []
        if isinstance(in_items, list):
            items = in_items
        else:
            # Expression
            try:
                items = eval(str(in_items), {"__builtins__": __builtins__}, ctx.variables)
                if not hasattr(items, '__iter__'):
                    raise ValueError(f"Result is not iterable: {type(items)}")
            except Exception as e:
                raise ScenarioExecutionError(f"Failed to evaluate for items '{in_items}': {e}", step=step)
                
        # Convert to list to avoid consuming iterators or issues with changes during iteration
        items_list = list(items)
        logger.info(f"Starting for loop: '{item_var}' in {len(items_list)} items")
        
        for i, item in enumerate(items_list):
            logger.info(f"For loop iteration {i+1}: {item_var} = {item}")
            ctx.set_variable(item_var, item)
            await self.execute_steps_callback(step.steps, ctx, defaults)
            
        ctx.add_result("for", True, {"var": item_var, "count": len(items_list)})


class SwitchStepExecutor(StepExecutor):
    """Executor for switch/case."""
    
    def __init__(self, container_manager, log_file=None, debug=False, execute_steps_callback=None):
        super().__init__(container_manager, log_file, debug)
        self.execute_steps_callback = execute_steps_callback
        
    async def execute(self, step: SwitchStep, ctx: RuntimeContext, defaults=None) -> None:
        """Execute switch step."""
        if not self.execute_steps_callback:
            raise RuntimeError("execute_steps_callback not set for SwitchStepExecutor")
            
        switch_expr = step.switch
        try:
            # Evaluate switch expression
            value = eval(switch_expr, {"__builtins__": __builtins__}, ctx.variables)
            # Convert to string to match keys
            match_value = str(value)
        except Exception as e:
            raise ScenarioExecutionError(f"Failed to evaluate switch expression '{switch_expr}': {e}", step=step)
            
        logger.info(f"Switch on '{switch_expr}' = {value} (match key: '{match_value}')")
        
        matched_steps = step.cases.get(match_value)
        
        if matched_steps:
            logger.info(f"Case '{match_value}' matched")
            await self.execute_steps_callback(matched_steps, ctx, defaults)
        elif step.default:
            logger.info("No case matched, executing default")
            await self.execute_steps_callback(step.default, ctx, defaults)
        else:
            logger.info("No case matched and no default")
            
        ctx.add_result("switch", True, {"switch": switch_expr, "value": match_value, "matched": bool(matched_steps)})

