# Экспорт ключевых файлов кода
## Дата: 25 декабря 2025

---

## 1. src/scenarios/step/data.py (ПОЛНЫЙ)

```python
"""
Data manipulation step executors (Extract, Count, NodeList, Join, Compute, Format, Assert, Log).
"""

import re
from typing import Any, Optional, List, Dict, Union

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import (
    AssertStep, LogStep, ExtractStep, CountStep, NodeListStep, JoinStep,
    ComputeStep, FormatStep
)
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class AssertStepExecutor(StepExecutor):
    """Executor for assert steps."""

    async def execute(self, step: AssertStep, ctx: RuntimeContext) -> None:
        """Execute assert step."""
        condition = step.condition

        # Substitute variables in condition
        substituted_condition = ctx.substitute(condition)

        try:
            result = eval(substituted_condition, {"__builtins__": __builtins__}, ctx.variables)
        except Exception as e:
            raise ScenarioExecutionError(f"Failed to evaluate assertion '{condition}': {e}", step=step)

        if not result:
            message = step.message or f"Assertion failed: {condition}"
            # Substitute variables in message
            message = ctx.substitute(message)
            raise ScenarioExecutionError(message, step=step)

        logger.info(f"✓ Assertion passed: {condition}")
        ctx.add_result("assert", True, {"condition": condition})


class LogStepExecutor(StepExecutor):
    """Executor for log steps."""

    async def execute(self, step: LogStep, ctx: RuntimeContext) -> None:
        """Execute log step."""
        message = ctx.substitute(step.message)
        level = step.level.lower()

        if level == "debug":
            logger.debug(message)
        elif level == "info":
            logger.info(message)
            print(message)  # Also print to stdout for visibility
        elif level == "warning":
            logger.warning(message)
            print(f"⚠️ {message}")
        elif level == "error":
            logger.error(message)
            print(f"❌ {message}")
        else:
            logger.info(message)
            print(message)

        ctx.add_result("log", True, {"message": message, "level": level})


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
    """Executor for node_list steps."""

    def _make_numeric_locals(self, ctx: RuntimeContext) -> dict:
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

    async def execute(self, step: NodeListStep, ctx: RuntimeContext) -> None:
        """Execute node_list step."""
        var_name = step.var_name
        prefix = step.prefix

        # Evaluate start and count
        start = step.start
        count = step.count

        # Build numeric locals for eval
        numeric_locals = self._make_numeric_locals(ctx)

        if isinstance(start, str):
            # First substitute {{variables}}
            start_str = ctx.substitute(str(start))
            # Try to convert to int, or evaluate as expression
            try:
                start = int(start_str)
            except ValueError:
                start = eval(start_str, {"__builtins__": __builtins__}, numeric_locals)

        if isinstance(count, str):
            # First substitute {{variables}}
            count_str = ctx.substitute(str(count))
            # Try to convert to int, or evaluate as expression
            try:
                count = int(count_str)
            except ValueError:
                count = eval(count_str, {"__builtins__": __builtins__}, numeric_locals)

        # Ensure both are integers
        start = int(start)
        count = int(count)

        # Generate node list
        nodes = [f"{prefix}{start + i}" for i in range(count)]
        ctx.set_variable(var_name, nodes)

        logger.info(f"Generated node list '{var_name}': {len(nodes)} nodes")
        ctx.add_result("node_list", True, {"variable": var_name, "count": len(nodes)})


class JoinStepExecutor(StepExecutor):
    """Executor for join steps."""

    def _make_numeric_locals(self, ctx: RuntimeContext) -> dict:
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

    async def execute(self, step: JoinStep, ctx: RuntimeContext) -> None:
        """Execute join step."""
        var_name = step.var_name
        separator = step.separator

        items = []

        if step.items is not None:
            # Use provided items list
            items = [ctx.substitute(item) for item in step.items]
        elif step.template is not None and step.range_count is not None:
            # Generate items from template and range
            range_count = step.range_count
            if isinstance(range_count, str):
                # First substitute {{variables}}
                range_str = ctx.substitute(str(range_count))
                # Try to convert to int, or evaluate as expression
                try:
                    range_count = int(range_str)
                except ValueError:
                    numeric_locals = self._make_numeric_locals(ctx)
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

    def _make_numeric_locals(self, ctx: RuntimeContext) -> dict:
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

    async def execute(self, step: ComputeStep, ctx: RuntimeContext) -> None:
        """Execute compute step."""
        var_name = step.var_name
        expr = step.expr

        # Build numeric locals for eval
        numeric_locals = self._make_numeric_locals(ctx)

        try:
            # Add useful builtins
            builtins_safe = {
                "__builtins__": {
                    "str": str, "int": int, "float": float,
                    "len": len, "range": range, "min": min, "max": max,
                    "sum": sum, "abs": abs, "round": round,
                    "list": list, "dict": dict, "set": set,
                    "True": True, "False": False, "None": None,
                }
            }
            result = eval(expr, builtins_safe, numeric_locals)
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
                # Substitute {{var}} references
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
```

---

## 2. src/scenarios/step/control_flow.py (КЛЮЧЕВЫЕ ЧАСТИ)

```python
"""
Control flow step executors (Set, If, While, For, Switch).
"""

class SetStepExecutor(StepExecutor):
    """Executor for set steps."""

    async def execute(self, step: SetStep, ctx: RuntimeContext) -> None:
        """Execute set step."""
        var_name = step.var_name
        value = step.value
        expr = step.expr

        if expr:
            # Evaluate expression
            try:
                result = eval(expr, {"__builtins__": __builtins__}, ctx.variables)
                ctx.set_variable(var_name, result)
            except Exception as e:
                raise ScenarioExecutionError(f"Failed to evaluate expression '{expr}': {e}")
        else:
            # Direct value assignment
            if isinstance(value, str):
                value = ctx.substitute(value)
            ctx.set_variable(var_name, value)


class IfStepExecutor(StepExecutor):
    """Executor for if steps."""

    async def execute(self, step: IfStep, ctx: RuntimeContext) -> None:
        """Execute if step."""
        condition = ctx.substitute(step.condition)
        
        try:
            result = eval(condition, {"__builtins__": __builtins__}, ctx.variables)
        except Exception as e:
            raise ScenarioExecutionError(f"Failed to evaluate condition '{condition}': {e}")

        if result:
            for sub_step in step.then_steps:
                await self._execute_sub_step(sub_step, ctx)
        elif step.else_steps:
            for sub_step in step.else_steps:
                await self._execute_sub_step(sub_step, ctx)


class ForStepExecutor(StepExecutor):
    """Executor for for loop steps."""

    async def execute(self, step: ForStep, ctx: RuntimeContext) -> None:
        """Execute for loop step."""
        var_name = step.loop_var
        iterable = step.iterable
        
        # Resolve iterable
        if isinstance(iterable, str):
            iterable = ctx.substitute(iterable)
            if iterable.startswith('[') and iterable.endswith(']'):
                iterable = eval(iterable, {"__builtins__": __builtins__}, ctx.variables)
            else:
                iterable = ctx.get_variable(iterable)
        
        for item in iterable:
            ctx.set_variable(var_name, item)
            for sub_step in step.steps:
                await self._execute_sub_step(sub_step, ctx)
```

---

## 3. src/scenarios/schema_data.py (ПОЛНЫЙ)

```python
"""
Pydantic schemas for data manipulation steps.
"""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict


class ExtractStep(BaseModel):
    """
    Extract value from string using regex pattern.
    
    Usage:
      - extract: hash
        source: "{{cli_output}}"
        pattern: "(0x[A-Fa-f0-9]{64})"
        group: 1
        default: null
    """
    extract: str = Field(..., description="Variable name to store extracted value")
    source: str = Field(..., description="Source string to extract from")
    pattern: str = Field(..., description="Regex pattern to match")
    group: int = Field(1, description="Capture group number (default 1)")
    default: Optional[str] = Field(None, description="Default value if no match")
    
    @property
    def var_name(self) -> str:
        return self.extract


class CountStep(BaseModel):
    """
    Count occurrences of pattern in string.
    
    Usage:
      - count: order_count
        source: "{{orders_list}}"
        pattern: "order:"
    """
    count: str = Field(..., description="Variable name to store count")
    source: str = Field(..., description="Source string to search in")
    pattern: str = Field(..., description="Pattern to count occurrences of")
    
    @property
    def var_name(self) -> str:
        return self.count


class NodeListStep(BaseModel):
    """
    Generate a list of node names.
    
    Usage:
      - node_list: root_nodes
        prefix: "node-"
        start: 1
        count: "{{root_count}}"
      
      - node_list: master_nodes
        prefix: "node-"
        start: "{{root_count + 1}}"
        count: "{{master_count}}"
    """
    node_list: str = Field(..., description="Variable name to store node list")
    prefix: str = Field("node-", description="Node name prefix")
    start: Union[int, str] = Field(1, description="Starting node number (can be expression)")
    count: Union[int, str] = Field(..., description="Number of nodes (can be expression)")
    
    @property
    def var_name(self) -> str:
        return self.node_list


class JoinStep(BaseModel):
    """
    Join items into a string with separator.
    
    Usage with items list:
      - join: validators_str
        items: ["node-5", "node-6", "node-7"]
        separator: ","
    
    Usage with template:
      - join: certs_str
        template: "stagenet.root.pvt.{i}"
        range_count: "{{root_count}}"
        separator: ","
    """
    join: str = Field(..., description="Variable name to store joined string")
    separator: str = Field(",", description="Separator between items")
    items: Optional[List[str]] = Field(None, description="List of items to join")
    template: Optional[str] = Field(None, description="Template for generating items (use {i} for index)")
    range_count: Optional[Union[int, str]] = Field(None, description="Number of items to generate from template")
    
    @property
    def var_name(self) -> str:
        return self.join


class ComputeStep(BaseModel):
    """
    Compute expression and store result.
    
    Usage:
      - compute: total
        expr: "root_count + master_count"
      
      - compute: next_idx
        expr: "current_idx + 1"
    """
    compute: str = Field(..., description="Variable name to store result")
    expr: str = Field(..., description="Python expression to evaluate")
    
    @property
    def var_name(self) -> str:
        return self.compute


class FormatStep(BaseModel):
    """
    Format string with variables.
    
    Usage:
      - format: message
        template: "Found {count} validators on {node}"
        count: "{{validator_count}}"
        node: "{{current_node}}"
    """
    model_config = ConfigDict(extra='allow')
    
    format: str = Field(..., description="Variable name to store formatted string")
    template: str = Field(..., description="Format template string")
    
    @property
    def var_name(self) -> str:
        return self.format


class AssertStep(BaseModel):
    """
    Assert condition is true.
    
    Usage:
      - assert: "{{validator_count}} >= 3"
        message: "Expected at least 3 validators"
    """
    assert_: str = Field(..., alias='assert', description="Condition to check")
    message: Optional[str] = Field(None, description="Error message if assertion fails")
    
    @property
    def condition(self) -> str:
        return self.assert_


class LogStep(BaseModel):
    """
    Log a message.
    
    Usage:
      - log: "Processing validators..."
        level: info
    """
    log: str = Field(..., description="Message to log")
    level: str = Field("info", description="Log level: debug, info, warning, error")
    
    @property
    def message(self) -> str:
        return self.log
```

---

## 4. src/scenarios/schema_control_flow.py (КЛЮЧЕВЫЕ ЧАСТИ)

```python
"""
Pydantic schemas for control flow steps.
"""

class SetStep(BaseModel):
    """
    Set a variable value.
    
    Usage:
      - set: my_var = "value"
      - set: my_var
        value: "some value"
      - set: my_var
        expr: "root_count + 1"
    """
    set: str = Field(..., description="Variable assignment (name = value) or just name")
    value: Optional[Any] = Field(None, description="Value to set (if not inline)")
    expr: Optional[str] = Field(None, description="Expression to evaluate")
    
    @property
    def var_name(self) -> str:
        if '=' in self.set:
            return self.set.split('=')[0].strip()
        return self.set


class IfStep(BaseModel):
    """
    Conditional execution.
    
    Usage:
      - if: "{{count}} > 0"
        then:
          - log: "Has items"
        else:
          - log: "No items"
    """
    if_: str = Field(..., alias='if', description="Condition to evaluate")
    then: List[Any] = Field(default_factory=list, description="Steps if true")
    else_: Optional[List[Any]] = Field(None, alias='else', description="Steps if false")
    
    @property
    def condition(self) -> str:
        return self.if_
    
    @property
    def then_steps(self) -> List[Any]:
        return self.then
    
    @property
    def else_steps(self) -> Optional[List[Any]]:
        return self.else_


class ForStep(BaseModel):
    """
    For loop over iterable.
    
    Usage:
      - for: node_idx
        in: "{{master_indices}}"
        steps:
          - cli: "node dump"
            node: "node-{{node_idx}}"
    """
    for_: str = Field(..., alias='for', description="Loop variable name")
    in_: Union[str, List[Any]] = Field(..., alias='in', description="Iterable to loop over")
    steps: List[Any] = Field(default_factory=list, description="Steps to execute each iteration")
    
    @property
    def loop_var(self) -> str:
        return self.for_
    
    @property
    def iterable(self) -> Union[str, List[Any]]:
        return self.in_
```

---

## 5. src/scenarios/global_context.py (КЛЮЧЕВЫЕ ЧАСТИ)

```python
class ScenarioGlobalContext:
    """Global context shared across scenarios with node information."""
    
    def __init__(
        self,
        network_name: str,
        topology_name: str,
        docker_client: Optional[docker.DockerClient] = None
    ):
        self.network_name = network_name
        self.topology_name = topology_name
        self.docker_client = docker_client or docker.from_env()
        
        # Node counts
        self.root_count = 0
        self.master_count = 0
        self.full_count = 0
        
        # Node lists
        self.all_nodes: List[str] = []
        self.root_nodes: List[str] = []
        self.master_nodes: List[str] = []
        self.full_nodes: List[str] = []
        self.seed_nodes: List[str] = []
        
        # Node indices
        self.root_indices: List[int] = []
        self.master_indices: List[int] = []
        self.full_indices: List[int] = []
        
        # IP addresses (collected after containers start)
        self.node_ip: Dict[str, str] = {}
    
    def set_static_node_info(self, node_configs: List[Any]) -> None:
        """Set static node information from configs."""
        for config in node_configs:
            node_name = f"node-{config.node_id}"
            self.all_nodes.append(node_name)
            
            if config.role == 'root':
                self.root_nodes.append(node_name)
                self.root_indices.append(config.node_id)
                self.root_count += 1
            elif config.role == 'master':
                self.master_nodes.append(node_name)
                self.master_indices.append(config.node_id)
                self.master_count += 1
            elif config.role == 'full':
                self.full_nodes.append(node_name)
                self.full_indices.append(config.node_id)
                self.full_count += 1
        
        self.seed_nodes = self.root_nodes.copy()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for variable injection."""
        return {
            'network_name': self.network_name,
            'topology_name': self.topology_name,
            'all_nodes': self.all_nodes,
            'root_nodes': self.root_nodes,
            'master_nodes': self.master_nodes,
            'full_nodes': self.full_nodes,
            'seed_nodes': self.seed_nodes,
            'root_count': self.root_count,
            'master_count': self.master_count,
            'full_count': self.full_count,
            'root_indices': self.root_indices,
            'master_indices': self.master_indices,
            'full_indices': self.full_indices,
            'first_root': self.root_nodes[0] if self.root_nodes else None,
            'first_master': self.master_nodes[0] if self.master_nodes else None,
            'second_root': self.root_nodes[1] if len(self.root_nodes) > 1 else None,
            'node_ip': self.node_ip,
        }
```

---

## 6. Genesis сценарий phase1_zerochain.yml (структура)

```yaml
name: PHASE 1 - Zerochain Genesis
description: Initialize ROOT nodes, create token and emission

includes:
  - ../common/set_net_default.yml

network:
  topology: default
  name: stagenet

setup:
  # Start nodes dynamically based on topology
  - docker_op: start
    services: "{{all_nodes}}"
  
  # Verify certificates exist
  - group: Verify ROOT node certificates
    # ... for loop checking certs
  
  # Copy root certs to node-1 for multi-signature
  - python: |
      # Copy all root certs to first node
  
  # Configure events_sign_cert for each ROOT
  - for: node_idx
    in: "{{root_indices}}"
    steps:
      - config: "stagenet"
        nodes: ["{{_current_node}}"]
        set:
          events_sign_cert: "{{_current_cert}}"
  
  - docker_op: restart
  - wait_network: online

test:
  # Get node addresses
  - group: Get node addresses
    # for loops to get addresses
  
  # Build validators_addrs (first 2 masters)
  - python: |
      # Only use first 2 master nodes as initial validators
  
  # Set validators_addrs on all nodes
  - config: "stagenet/main"
    nodes: "{{all_nodes}}"
    set:
      validators_addrs: "{{validators_addrs_str}}"
  
  # Add nodes to nodelist
  # Create wallets
  # Get fee_addr
  # Enable seed_mode
  
  # Genesis Event - Token Declaration
  - group: Genesis Event - Token Declaration
    steps:
      - cli: "token_decl -token TCELL ..."
        save_hash: token_hash
      - cli: "mempool proc -datum {{token_hash}}"
      - cli: "dag event last -chain zerochain"
        save_hash: genesis_event_hash
  
  # Set static genesis event
  - config: "stagenet/zerochain"
    set:
      static_genesis_event: "{{genesis_event_hash}}"
  
  # Create stake orders for initial validators
  # Token Emission
```

---

*Экспорт кода завершён: 25 декабря 2025*

