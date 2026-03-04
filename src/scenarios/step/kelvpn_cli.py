"""
KelvpnCli step executor.

Thin wrapper around KelVPNCli that behaves like CLIStep but always targets
/opt/kelvpn/bin/KelVPNCli.  The command is always guarded by ``timeout N``
and ``|| true`` so it never fails the step — use ``contains`` / ``not_contains``
for assertions.
"""

from typing import Any, Dict

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema import KelvpnCliStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)

_KELVPN_CLI = "/opt/kelvpn/bin/KelVPNCli"


class KelvpnCliStepExecutor(StepExecutor):
    """Executor for kelvpn_cli: steps."""

    async def execute(self, step: KelvpnCliStep, ctx: RuntimeContext) -> Dict[str, Any]:
        args = ctx.substitute(step.kelvpn_cli)
        node = ctx.substitute(step.node)
        timeout = step.timeout

        script = f"timeout {timeout} {_KELVPN_CLI} {args} 2>&1 || true"

        desc = ctx.substitute(step.description) if step.description else f"KelVPNCli {args}"
        logger.info("kelvpn_cli_step", node=node, args=args, timeout=timeout, description=desc)

        result = await self.container_manager.exec_bash_command(
            script=script,
            node=node,
            timeout=timeout + 5,  # outer timeout slightly larger than inner
        )

        stdout: str = result.get("stdout", "")

        if step.save:
            ctx.set_variable(step.save, stdout)
            logger.debug("kelvpn_cli_saved", variable=step.save)

        if step.contains and step.contains not in stdout:
            raise ScenarioExecutionError(
                f"kelvpn_cli: expected output to contain {step.contains!r}",
                step=script,
                context={"stdout": stdout[:500]},
            )

        if step.not_contains and step.not_contains in stdout:
            raise ScenarioExecutionError(
                f"kelvpn_cli: output must NOT contain {step.not_contains!r}",
                step=script,
                context={"stdout": stdout[:500]},
            )

        return result
