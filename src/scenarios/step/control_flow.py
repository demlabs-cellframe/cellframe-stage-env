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
        import re as regex_module
        
        var_name = ctx.substitute(step.set)
        
        if step.eval:
            # Evaluate expression using context variables
            expr = str(step.value)
            
            # Built-in helper functions available in eval
            def join_vars(prefix: str, count: int, separator: str = ",") -> str:
                """Join variables with common prefix: join_vars('addr_', 3) -> 'val0,val1,val2'"""
                values = [str(ctx.variables.get(f"{prefix}{i}", "")) for i in range(count)]
                return separator.join(values)
            
            def join_vars_bracket(prefix: str, count: int, separator: str = ",") -> str:
                """Join variables with brackets: join_vars_bracket('addr_', 3) -> '[val0,val1,val2]'"""
                return "[" + join_vars(prefix, count, separator) + "]"
            
            def regex_extract(text: str, pattern: str, group: int = 1) -> str:
                """Extract first match: regex_extract(text, r'hash:\s*(\w+)', 1)"""
                match = regex_module.search(pattern, str(text))
                if match:
                    return match.group(group)
                return ""
            
            def find_all(text: str, pattern: str) -> list:
                """Find all matches: find_all(text, r'[A-Z0-9]{4}-...')"""
                return regex_module.findall(pattern, str(text))
            
            def concat(*args) -> str:
                """Concatenate values: concat('a', '-', 'b') -> 'a-b'"""
                return "".join(str(a) for a in args)
            
            def get_var(name: str, default: str = "") -> str:
                """Get variable by dynamic name: get_var('addr_' + str(i))"""
                return str(ctx.variables.get(name, default))
            
            def get_var_dict(name: str) -> dict:
                """Get dict variable: get_var_dict('node_ip')"""
                return ctx.variables.get(name, {})
            
            try:
                # Add helper functions to eval namespace
                eval_globals = {
                    "__builtins__": __builtins__,
                    "join_vars": join_vars,
                    "join_vars_bracket": join_vars_bracket,
                    "regex_extract": regex_extract,
                    "find_all": find_all,
                    "concat": concat,
                    "get_var": get_var,
                    "get_var_dict": get_var_dict,
                    "range": range,
                    "len": len,
                    "str": str,
                    "int": int,
                    "list": list,
                    "re": regex_module,
                }
                eval_globals.update(ctx.variables)
                value = eval(expr, eval_globals)
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
            eval_ns = {"__builtins__": __builtins__, "str": str, "int": int, "len": len, "range": range, "ctx": ctx}
            eval_ns.update(ctx.variables)
            result = eval(condition, eval_ns)
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
                eval_ns = {"__builtins__": __builtins__, "str": str, "int": int, "len": len, "range": range, "ctx": ctx}
                eval_ns.update(ctx.variables)
                result = eval(condition, eval_ns)
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
            # String - could be template or expression
            # First substitute any Jinja2 templates
            substituted = ctx.substitute(str(in_items))
            
            # Try to parse as list literal first
            if substituted.startswith('[') and substituted.endswith(']'):
                import ast
                try:
                    items = ast.literal_eval(substituted)
                except (ValueError, SyntaxError):
                    # Fallback to eval
                    try:
                        for_globals = {"__builtins__": __builtins__, "range": range, "len": len, "str": str, "int": int, "list": list}
                        for_globals.update(ctx.variables)
                        items = eval(substituted, for_globals)
                    except Exception as e:
                        raise ScenarioExecutionError(f"Failed to evaluate for items '{in_items}': {e}", step=step)
            else:
                # Try as Python expression
                try:
                    for_globals = {"__builtins__": __builtins__, "range": range, "len": len, "str": str, "int": int, "list": list}
                    for_globals.update(ctx.variables)
                    items = eval(substituted, for_globals)
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
            switch_globals = {"__builtins__": __builtins__, "str": str, "int": int}
            switch_globals.update(ctx.variables)
            value = eval(switch_expr, switch_globals)
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

