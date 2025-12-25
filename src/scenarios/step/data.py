"""
Data manipulation step executors (Extract, Count, Join, Compute, Format, NodeList).
"""

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import ExtractStep, CountStep, NodeListStep, JoinStep, ComputeStep, FormatStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


def _make_numeric_locals(ctx: RuntimeContext) -> dict:
    """Convert string variables to numbers where possible for eval."""
    numeric_locals = {}
    for key, value in ctx.variables.items():
        if isinstance(value, str):
            try:
                numeric_locals[key] = int(value)
            except ValueError:
                try:
                    numeric_locals[key] = float(value)
                except ValueError:
                    numeric_locals[key] = value
        else:
            numeric_locals[key] = value
    return numeric_locals


class ExtractStepExecutor(StepExecutor):
    """Executor for extract steps (regex extraction)."""
    
    async def execute(self, step: ExtractStep, ctx: RuntimeContext) -> None:
        """Execute extract step."""
        import re
        
        var_name = step.var_name
        source = ctx.substitute(step.source)
        pattern = step.pattern
        group = step.group
        default = step.default
        
        try:
            match = re.search(pattern, source)
            if match:
                value = match.group(group)
                ctx.set_variable(var_name, value)
                logger.info(f"Extracted '{var_name}' = {value[:50]}..." if len(str(value)) > 50 else f"Extracted '{var_name}' = {value}")
            elif default is not None:
                ctx.set_variable(var_name, default)
                logger.info(f"No match, using default '{var_name}' = {default}")
            else:
                raise ScenarioExecutionError(f"Pattern '{pattern}' not found in source", step=step)
            
            ctx.add_result("extract", True, {"variable": var_name})
            
        except re.error as e:
            raise ScenarioExecutionError(f"Invalid regex pattern '{pattern}': {e}", step=step)


class CountStepExecutor(StepExecutor):
    """Executor for count steps."""
    
    async def execute(self, step: CountStep, ctx: RuntimeContext) -> None:
        """Execute count step."""
        var_name = step.var_name
        source = ctx.substitute(step.source)
        pattern = ctx.substitute(step.pattern)
        
        count = source.count(pattern)
        ctx.set_variable(var_name, count)
        
        logger.info(f"Count '{var_name}' = {count}")
        ctx.add_result("count", True, {"variable": var_name, "count": count})


class NodeListStepExecutor(StepExecutor):
    """Executor for node_list steps - generates list of node names."""
    
    async def execute(self, step: NodeListStep, ctx: RuntimeContext) -> None:
        """Execute node_list step."""
        var_name = step.var_name
        prefix = step.prefix
        
        # Evaluate start and count
        start = step.start
        count = step.count
        
        # Build numeric locals for eval
        numeric_locals = _make_numeric_locals(ctx)
        
        if isinstance(start, str):
            start_str = ctx.substitute(str(start))
            try:
                start = int(start_str)
            except ValueError:
                start = eval(start_str, {"__builtins__": __builtins__}, numeric_locals)
        
        if isinstance(count, str):
            count_str = ctx.substitute(str(count))
            try:
                count = int(count_str)
            except ValueError:
                count = eval(count_str, {"__builtins__": __builtins__}, numeric_locals)
        
        start = int(start)
        count = int(count)
        
        # Generate node list
        nodes = [f"{prefix}{start + i}" for i in range(count)]
        ctx.set_variable(var_name, nodes)
        
        logger.info(f"Generated node list '{var_name}': {len(nodes)} nodes")
        ctx.add_result("node_list", True, {"variable": var_name, "count": len(nodes)})


class JoinStepExecutor(StepExecutor):
    """Executor for join steps."""
    
    async def execute(self, step: JoinStep, ctx: RuntimeContext) -> None:
        """Execute join step."""
        var_name = step.var_name
        separator = step.separator
        
        items = []
        
        if step.items is not None:
            items = [ctx.substitute(item) for item in step.items]
        elif step.template is not None and step.range_count is not None:
            range_count = step.range_count
            if isinstance(range_count, str):
                range_str = ctx.substitute(str(range_count))
                try:
                    range_count = int(range_str)
                except ValueError:
                    numeric_locals = _make_numeric_locals(ctx)
                    range_count = eval(range_str, {"__builtins__": __builtins__}, numeric_locals)
            
            range_count = int(range_count)
            template = step.template
            for i in range(range_count):
                item = template.replace("{i}", str(i))
                items.append(ctx.substitute(item))
        else:
            raise ScenarioExecutionError("Join step requires either 'items' or 'template' + 'range'", step=step)
        
        result = separator.join(items)
        ctx.set_variable(var_name, result)
        
        logger.info(f"Joined '{var_name}' = {result[:50]}..." if len(result) > 50 else f"Joined '{var_name}' = {result}")
        ctx.add_result("join", True, {"variable": var_name, "items_count": len(items)})


class ComputeStepExecutor(StepExecutor):
    """Executor for compute steps (expression evaluation)."""
    
    async def execute(self, step: ComputeStep, ctx: RuntimeContext) -> None:
        """Execute compute step."""
        var_name = step.var_name
        expr = step.expr
        
        numeric_locals = _make_numeric_locals(ctx)
        
        # Helper function to get variable with default value
        def get_var(name: str, default=None):
            """Get variable by name with optional default."""
            return numeric_locals.get(name, ctx.variables.get(name, default))
        
        # Helper to check if variable exists
        def has_var(name: str) -> bool:
            """Check if variable exists."""
            return name in numeric_locals or name in ctx.variables
        
        try:
            # Combine builtins with variables in globals for proper scope in comprehensions
            eval_globals = {
                "__builtins__": {
                    "str": str, "int": int, "float": float,
                    "len": len, "range": range, "min": min, "max": max,
                    "sum": sum, "abs": abs, "round": round,
                    "list": list, "dict": dict, "set": set,
                    "True": True, "False": False, "None": None,
                    "get_var": get_var,
                    "has_var": has_var,
                },
                # Include variables in globals so they're visible in comprehensions
                **numeric_locals
            }
            result = eval(expr, eval_globals, {})
            ctx.set_variable(var_name, result)
            
            logger.info(f"Computed '{var_name}' = {result}")
            ctx.add_result("compute", True, {"variable": var_name, "value": str(result)})
            
        except Exception as e:
            raise ScenarioExecutionError(f"Failed to compute expression '{expr}': {e}", step=step)


class FormatStepExecutor(StepExecutor):
    """Executor for format steps (string formatting)."""
    
    async def execute(self, step: FormatStep, ctx: RuntimeContext) -> None:
        """Execute format step."""
        var_name = step.var_name
        template = step.template
        
        # Get all extra fields as format vars
        format_vars = {}
        for key, value in step.model_extra.items():
            if isinstance(value, str):
                format_vars[key] = ctx.substitute(value)
            else:
                format_vars[key] = value
        
        # Also include context variables
        for key, value in ctx.variables.items():
            if key not in format_vars:
                format_vars[key] = value
        
        try:
            result = template.format(**format_vars)
            ctx.set_variable(var_name, result)
            
            logger.info(f"Formatted '{var_name}' = {result}")
            ctx.add_result("format", True, {"variable": var_name, "value": result})
            
        except KeyError as e:
            raise ScenarioExecutionError(f"Missing format variable: {e}", step=step)
        except Exception as e:
            raise ScenarioExecutionError(f"Failed to format template '{template}': {e}", step=step)

