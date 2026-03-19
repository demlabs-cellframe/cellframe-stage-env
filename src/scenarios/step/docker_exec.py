"""
Docker exec shorthand step executor.

Provides a compact ``docker_exec`` step that delegates to the
compose manager's ``exec()`` without the ``docker_op: exec`` boilerplate.
"""

from ...utils.logger import get_logger
from .base import StepExecutor, resolve_timeout
from ..schema import DockerExecStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)


class DockerExecStepExecutor(StepExecutor):
    """Executor for the ``docker_exec`` shorthand step."""

    def __init__(self, container_manager, log_file=None, debug=False,
                 resolve_node_alias_callback=None):
        super().__init__(container_manager, log_file, debug)
        self.resolve_node_alias_callback = resolve_node_alias_callback

    async def execute(self, step: DockerExecStep, ctx: RuntimeContext) -> None:
        command_str = ctx.substitute(step.docker_exec)
        command_parts = ["sh", "-c", command_str]

        raw_services = step.services
        if isinstance(raw_services, str):
            expanded = ctx.substitute(raw_services)
            if expanded.startswith('[') and expanded.endswith(']'):
                import ast
                try:
                    raw_services = ast.literal_eval(expanded)
                except (ValueError, SyntaxError):
                    raw_services = [expanded]
            else:
                raw_services = [s.strip() for s in expanded.split(',') if s.strip()]
        services = [ctx.substitute(s) for s in raw_services]

        if not hasattr(ctx, 'compose_manager'):
            raise ScenarioExecutionError(
                "DockerComposeManager not available in context.",
                step=step,
            )

        compose_manager = ctx.compose_manager
        all_output = []

        for svc in services:
            logger.info(f"docker_exec on {svc}: {command_str[:120]}")
            exit_code, output = compose_manager.exec(service=svc, command=command_parts)
            logger.info(f"docker_exec {svc}: exit_code={exit_code}, output={output[:200]}")

            if step.expect == "success" and exit_code != 0:
                raise ScenarioExecutionError(
                    f"docker_exec failed on {svc}: exit_code={exit_code}, output={output}",
                    step=step,
                )
            elif step.expect == "error" and exit_code == 0:
                raise ScenarioExecutionError(
                    f"docker_exec succeeded on {svc} but expected error",
                    step=step,
                )
            all_output.append(output)

        combined = "\n".join(all_output)
        if step.save or step.save_map:
            ctx.save_output(combined, step.save, step.save_regex, step.save_map)

        ctx.add_result("docker_exec", True, {
            "command": command_str, "services": services
        })
