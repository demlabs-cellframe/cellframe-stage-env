"""
Executor for custom operand steps.

Resolves the operand action's step sequence from the registry,
injects caller-supplied parameters as context variables, and
delegates execution to the standard ``_execute_steps`` callback.
"""

import copy
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

        logger.info(
            f"Custom operand: {operand_name}.{action_name}",
            params=list(step.operand_params.keys()),
            inner_steps=len(raw_steps),
        )

        saved_vars: Dict[str, Any] = {}
        try:
            # Merge defaults from operand definition with caller-supplied params.
            # Caller params take precedence over operand-declared defaults.
            action_defaults = defn.get_action_defaults(action_name)
            effective_params = {**action_defaults, **step.operand_params}

            for key, value in effective_params.items():
                if isinstance(value, str):
                    value = ctx.substitute(value)
                saved_vars[key] = ctx.get_variable(key) if ctx.has_variable(key) else _SENTINEL
                ctx.set_variable(key, value)

            from ..schema import TestStep
            adapter = TypeAdapter(List[TestStep])
            parsed_steps = adapter.validate_python(copy.deepcopy(raw_steps))

            await self._execute_steps(parsed_steps, ctx, defaults)
        finally:
            for key, prev in saved_vars.items():
                if prev is _SENTINEL:
                    ctx.delete_variable(key)
                else:
                    ctx.set_variable(key, prev)


_SENTINEL = object()
