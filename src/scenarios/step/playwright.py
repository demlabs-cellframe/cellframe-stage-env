"""
Playwright spec step executor.

Runs Playwright test specs inside a browser runner container that is part
of the stage-env Docker cluster.
"""

import asyncio
import json
import re
from typing import Any, Dict

from ...utils.logger import get_logger
from .base import StepExecutor, resolve_timeout
from ..schema import PlaywrightStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)

_OUTPUT_VAR_RE = re.compile(r"^::set-output\s+(\w+)=(.*)$", re.MULTILINE)


class PlaywrightStepExecutor(StepExecutor):
    """Executor for Playwright browser test steps.

    Builds a ``npx playwright test`` command, executes it inside the
    playwright-runner container and optionally captures output variables
    that specs emit via ``console.log('::set-output VAR=value')``.
    """

    async def execute(self, step: PlaywrightStep, ctx: RuntimeContext) -> Dict[str, Any]:
        env_vars: Dict[str, str] = {}
        for k, v in step.env.items():
            env_vars[k] = ctx.substitute(v)

        env_str = " ".join(f"{k}={shlex_quote(v)}" for k, v in env_vars.items())

        cmd_parts = [
            env_str,
            "npx", "playwright", "test", step.playwright,
            f"--project={step.browser}",
            "--reporter=line",
        ]
        if step.headed:
            cmd_parts.append("--headed")

        cmd = " ".join(p for p in cmd_parts if p)

        timeout = resolve_timeout(step.timeout, ctx, default=120)
        logger.info(
            "playwright_exec",
            spec=step.playwright,
            browser=step.browser,
            container=step.container,
            timeout=timeout,
        )

        try:
            result = await self.container_manager.exec_bash_command(
                script=cmd,
                node=step.container,
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise ScenarioExecutionError(
                f"Playwright spec timed out after {timeout}s: {step.playwright}",
                step=step.playwright,
                context={"timeout": timeout, "browser": step.browser},
            )

        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        returncode = result.get("returncode", 1)

        logger.info(
            "playwright_result",
            spec=step.playwright,
            returncode=returncode,
            stdout_preview=stdout[:500] if stdout else "",
        )

        if step.save and stdout:
            for match in _OUTPUT_VAR_RE.finditer(stdout):
                out_key = match.group(1)
                out_val = match.group(2).strip()
                if out_key in step.save:
                    ctx_var = ctx.substitute(step.save[out_key])
                    ctx.set_variable(ctx_var, out_val)
                    logger.info(
                        "playwright_save_var",
                        spec_key=out_key,
                        ctx_var=ctx_var,
                        value_preview=out_val[:80],
                    )

        success = returncode == 0
        expect_success = step.expect in ("success", "SUCCESS")

        if expect_success and not success:
            raise ScenarioExecutionError(
                f"Playwright spec failed (exit {returncode}): {step.playwright}",
                step=step.playwright,
                context={
                    "returncode": returncode,
                    "stdout": stdout[-2000:] if stdout else "",
                    "stderr": stderr[-2000:] if stderr else "",
                },
            )
        if not expect_success and success:
            raise ScenarioExecutionError(
                f"Playwright spec unexpectedly passed: {step.playwright}",
                step=step.playwright,
                context={"returncode": returncode},
            )

        return result


def shlex_quote(s: str) -> str:
    """Portable single-quote escaping (subset of shlex.quote)."""
    if not s:
        return "''"
    if re.search(r"[^\w@%+=:,./-]", s):
        return "'" + s.replace("'", "'\"'\"'") + "'"
    return s
