"""
Executor for custom operand steps.

Resolves the operand action's step sequence from the registry,
injects caller-supplied parameters as context variables, and
delegates execution to the standard ``_execute_steps`` callback.
"""

import copy
import re
from typing import Any, Callable, Coroutine, Dict, List, Optional

from pydantic import TypeAdapter

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema_operand import CustomOperandStep
from ..operand_registry import OperandRegistry
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class CustomOperandStepExecutor(StepExecutor):
    """Executor for custom operand steps."""

    def __init__(self, container_manager, log_file, debug,
                 registry: OperandRegistry,
                 execute_steps_callback: Callable):
        super().__init__(container_manager, log_file, debug)
        self._registry = registry
        self._execute_steps = execute_steps_callback

    async def execute(self, step: CustomOperandStep, ctx: RuntimeContext, defaults=None) -> None:
        operand_name = ctx.substitute(step.operand_name)
        action_name = ctx.substitute(step.operand_action)

        if not self._registry.is_operand(operand_name):
            raise ScenarioExecutionError(
                f"Unknown custom operand '{operand_name}'. "
                f"Registered: {sorted(self._registry.names)}"
            )

        defn = self._registry.get(operand_name)
        raw_steps = defn.get_action_steps(action_name)

        action_def = defn.actions.get(action_name, {})
        action_defaults = action_def.get("params", {})

        logger.info(
            f"Custom operand: {operand_name}.{action_name}",
            params=list(step.operand_params.keys()),
            inner_steps=len(raw_steps),
        )

        merged_params = {**action_defaults, **step.operand_params}

        if defaults and defaults.node and "node" not in merged_params:
            merged_params["node"] = defaults.node

        saved_vars: Dict[str, Any] = {}
        try:
            for key, value in merged_params.items():
                if isinstance(value, str):
                    resolved = ctx.substitute(value)
                    ref_match = _SINGLE_VAR_RE.fullmatch(value)
                    if ref_match and ctx.has_variable(ref_match.group(1)):
                        value = ctx.get_variable(ref_match.group(1))
                    else:
                        value = resolved
                saved_vars[key] = ctx.get_variable(key) if ctx.has_variable(key) else _SENTINEL
                ctx.set_variable(key, value)

            logger.info("operand_vars_before_execute",
                        saved_keys=list(saved_vars.keys()),
                        ctx_vars=list(ctx.variables.keys()))

            from ..schema import TestStep
            adapter = TypeAdapter(List[TestStep])
            parsed_steps = adapter.validate_python(copy.deepcopy(raw_steps))

            await self._execute_steps(parsed_steps, ctx, defaults)

            logger.info("operand_vars_after_execute",
                        ctx_vars=list(ctx.variables.keys()))
        finally:
            for key, prev in saved_vars.items():
                if prev is _SENTINEL:
                    ctx.delete_variable(key)
                else:
                    ctx.set_variable(key, prev)
            logger.info("operand_vars_after_cleanup",
                        ctx_vars=list(ctx.variables.keys()))


_SENTINEL = object()
_SINGLE_VAR_RE = re.compile(r'^\{\{(\w+)\}\}$')
