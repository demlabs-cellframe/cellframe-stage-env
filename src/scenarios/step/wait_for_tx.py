"""
Wait-for-tx step executor.

Waits for common transaction to complete through few verification stages depending on the expected scenario:

expected_status='success':
  1. Validate format for the recieved hash of transaction (0x + 64 hex)
  2. Check for certain transaction appearance in mempool ('find: true' & 'source: mempool')
  3. Check for certain transaction to reach the chain ('find: true' & 'source: chain')
  4. Check for new block (main) or DAG event (zerochain) containing the transaction to appear in network
     (block find / dag event find: total: 1, output contains at least one 0x+64hex hash)

expected_status='failure':
  1. Validate format for the recieved hash of transaction (0x + 64 hex)
  2. Check for certain transaction appearance in mempool ('find: true' & 'status: hole')
  3. Check for new block (main) or DAG event (zerochain) containing the transaction to NOT appear in network
     (block find / dag event find: total: 0, no 0x+64hex hashes)

After success: waits 5 seconds before continuing.
"""

import asyncio
import re

from ...utils.logger import get_logger
from ...utils.chain_type import chain_uses_dag
from .base import StepExecutor
from ..schema import WaitForTxStep
from ..executor import ScenarioExecutionError, RuntimeContext

logger = get_logger(__name__)

HASH_PATTERN = re.compile(r'^0x[0-9a-fA-F]{64,}$')
HASH_IN_OUTPUT = re.compile(r'0x[0-9a-fA-F]{64,}')


def format_tx_hash_preview(tx_hash: str) -> str:
    """Formatting transaction hash for logs informativity: 0x1234...5678."""
    if len(tx_hash) >= 14:
        return tx_hash[:6] + "..." + tx_hash[-4:]
    return tx_hash


class WaitForTxStepExecutor(StepExecutor):
    """Executor for wait-for-tx steps."""

    async def execute(self, step: WaitForTxStep, ctx: RuntimeContext) -> None:
        """Execute wait-for-tx step."""
        tx_hash = ctx.substitute(step.wait_for_tx)
        expected_status = ctx.substitute(step.expected_status)
        network = ctx.substitute(step.network) if step.network else "stagenet"
        chain = ctx.substitute(step.chain) if step.chain else "main"
        node = ctx.substitute(step.node) if step.node else "node1"
        timeout = step.timeout_per_stage
        interval = step.check_interval

        logger.info(
            f"Tracking specified transaction: '{format_tx_hash_preview(tx_hash)}' "
            f"(network={network}, node={node}, expected_status={expected_status})"
        )

        if not HASH_PATTERN.match(tx_hash):
            raise ScenarioExecutionError(
                f"Invalid specified transaction hash format: '{format_tx_hash_preview(tx_hash)}'. Expected 0x + 64+ hex chars.",
                step=step,
                context={"error": "invalid_hash_format"}
            )

        if expected_status == "success":
            await self._execute_success_flow(tx_hash, node, network, chain, timeout, interval, step)
        elif expected_status == "failure":
            await self._execute_failure_flow(tx_hash, node, network, chain, timeout, interval, step)
        else:
            raise ScenarioExecutionError(
                f"Invalid key for 'expected_status' parameter: '{expected_status}'. Must be 'success' or 'failure'.",
                step=step,
                context={"error": "invalid_expected_status"}
            )

        await asyncio.sleep(5)
        ctx.add_result("wait_for_tx", True, {"tx_hash": format_tx_hash_preview(tx_hash), "expected_status": expected_status})

    async def _execute_success_flow(
        self, tx_hash: str, node: str, network: str, chain: str,
        timeout: int, interval: int, step: WaitForTxStep
    ) -> None:
        """Success flow for the specified transaction: mempool → chain → block."""
        await self._wait_stage(
            name="mempool",
            tx_hash=tx_hash,
            check_success_fn=lambda: self._check_mempool_success(node, network, chain, tx_hash),
            timeout=timeout,
            interval=interval,
            error_code="timeout_mempool_verification",
            step=step,
        )
        await self._wait_stage(
            name="chain",
            tx_hash=tx_hash,
            check_success_fn=lambda: self._check_chain(node, network, chain, tx_hash),
            timeout=timeout,
            interval=interval,
            error_code="timeout_chain_verification",
            step=step,
        )
        if chain_uses_dag(chain, network=network):
            await self._wait_stage(
                name="dag event",
                tx_hash=tx_hash,
                check_success_fn=lambda: self._check_dag_event_success(node, network, tx_hash),
                timeout=timeout,
                interval=interval,
                error_code="timeout_dag_event_verification",
                step=step,
            )
            logger.info(
                f"Specified transaction '{format_tx_hash_preview(tx_hash)}' successfully passed 'mempool', "
                f"'chain' and was confirmed in 'events'"
            )
        else:
            await self._wait_stage(
                name="block",
                tx_hash=tx_hash,
                check_success_fn=lambda: self._check_block_success(node, network, tx_hash),
                timeout=timeout,
                interval=interval,
                error_code="timeout_block_verification",
                step=step,
            )
            logger.info(
                f"Specified transaction '{format_tx_hash_preview(tx_hash)}' successfully passed 'mempool', "
                f"'chain' and was confirmed in 'blocks'"
            )

    async def _execute_failure_flow(
        self, tx_hash: str, node: str, network: str, chain: str,
        timeout: int, interval: int, step: WaitForTxStep
    ) -> None:
        """Failure flow for the specified transaction: mempool (status: hole) → block (total: 0) / event (total: 0)."""
        await self._wait_stage(
            name="mempool (status: hole)",
            tx_hash=tx_hash,
            check_success_fn=lambda: self._check_mempool_failure(node, network, chain, tx_hash),
            timeout=timeout,
            interval=interval,
            error_code="timeout_mempool_failure_verification",
            step=step,
        )
        if chain_uses_dag(chain, network=network):
            await self._wait_stage(
                name="dag event (total: 0)",
                tx_hash=tx_hash,
                check_success_fn=lambda: self._check_dag_event_failure(node, network, tx_hash),
                timeout=timeout,
                interval=interval,
                error_code="timeout_dag_event_failure_verification",
                step=step,
            )
        else:
            await self._wait_stage(
                name="block (total: 0)",
                tx_hash=tx_hash,
                check_success_fn=lambda: self._check_block_failure(node, network, tx_hash),
                timeout=timeout,
                interval=interval,
                error_code="timeout_block_failure_verification",
                step=step,
            )
        logger.info(f"Specified transaction '{format_tx_hash_preview(tx_hash)}' was correctly rejected by ledger, as expected")

    async def _wait_stage(
        self,
        name: str,
        tx_hash: str,
        check_success_fn,
        timeout: int,
        interval: int,
        error_code: str,
        step: WaitForTxStep,
    ) -> None:
        """Repeatedly call 'check_success_fn' until it returns 'True', or timeout."""
        start = asyncio.get_event_loop().time()
        attempt = 0
        while True:
            attempt += 1
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed >= timeout:
                raise ScenarioExecutionError(
                    f"Specified transaction '{format_tx_hash_preview(tx_hash)}' tracking in '{name}' timeout exceeded after {timeout}s ({attempt} attempts)",
                    step=step,
                    context={"error": error_code, "attempts": attempt}
                )
            try:
                success = await check_success_fn()
                if success:
                    logger.info(f"Specified transaction '{format_tx_hash_preview(tx_hash)}' successfully reached the '{name}' after {attempt} attempt(s)")
                    return
            except ScenarioExecutionError:
                raise
            except Exception as e:
                logger.warning(f"Specified transaction '{format_tx_hash_preview(tx_hash)}' failed to reach the '{name}' after {attempt} attempt(s): {e}")
            await asyncio.sleep(interval)

    async def _run_cli(self, node: str, command: str) -> tuple[int, str, str]:
        """Run 'CLI' command and return (exit_code, stdout, stderr)."""
        result = await self.container_manager.exec_cli_command(
            command=command,
            node=node,
            timeout=30
        )
        stdout = result.get("stdout", "") or ""
        stderr = result.get("stderr", "") or ""
        return result.get("returncode", 1), stdout, stderr

    async def _check_mempool_success(self, node: str, network: str, chain: str, tx_hash: str) -> bool:
        """Success: specified transaction has 'find: true' and 'source: mempool' in mempool check output."""
        cmd = f"mempool check -net {network} -chain {chain} -datum {tx_hash}"
        exit_code, stdout, _ = await self._run_cli(node, cmd)
        if exit_code != 0:
            return False
        return "find: true" in stdout and "source: mempool" in stdout

    async def _check_mempool_failure(self, node: str, network: str, chain: str, tx_hash: str) -> bool:
        """Failure: specified transaction has 'find: true' and 'status: hole' in mempool check output."""
        cmd = f"mempool check -net {network} -chain {chain} -datum {tx_hash}"
        exit_code, stdout, _ = await self._run_cli(node, cmd)
        if exit_code != 0:
            return False
        return "find: true" in stdout and "status: hole" in stdout

    async def _check_chain(self, node: str, network: str, chain: str, tx_hash: str) -> bool:
        """Success: specified transaction has 'find: true' and 'source: chain' in mempool check output."""
        cmd = f"mempool check -net {network} -chain {chain} -datum {tx_hash}"
        exit_code, stdout, _ = await self._run_cli(node, cmd)
        if exit_code != 0:
            return False
        return "find: true" in stdout and "source: chain" in stdout

    async def _check_block_success(self, node: str, network: str, tx_hash: str) -> bool:
        """Success: specified transaction has 'total: 1' and at least one block hash in block find output."""
        cmd = f"block find -net {network} -datum {tx_hash}"
        exit_code, stdout, _ = await self._run_cli(node, cmd)
        if exit_code != 0:
            return False
        if "total: 1" not in stdout:
            return False
        block_hashes = HASH_IN_OUTPUT.findall(stdout)
        return len(block_hashes) >= 1

    async def _check_dag_event_success(self, node: str, network: str, tx_hash: str) -> bool:
        """Success: specified datum has at least one event hash in dag event find output."""
        cmd = f"dag event find -net {network} -datum {tx_hash}"
        exit_code, stdout, _ = await self._run_cli(node, cmd)
        if exit_code != 0:
            return False
        event_hashes = HASH_IN_OUTPUT.findall(stdout)
        return len(event_hashes) >= 1

    async def _check_block_failure(self, node: str, network: str, tx_hash: str) -> bool:
        """Failure: specified transaction has 'total: 0' and no block hash in block find output."""
        cmd = f"block find -net {network} -datum {tx_hash}"
        exit_code, stdout, _ = await self._run_cli(node, cmd)
        if exit_code != 0:
            return False
        if "total: 0" not in stdout:
            return False
        block_hashes = HASH_IN_OUTPUT.findall(stdout)
        return len(block_hashes) == 0

    async def _check_dag_event_failure(self, node: str, network: str, tx_hash: str) -> bool:
        """Failure: specified datum has no event hash in dag event find output."""
        cmd = f"dag event find -net {network} -datum {tx_hash}"
        exit_code, stdout, _ = await self._run_cli(node, cmd)
        if exit_code != 0:
            return False
        event_hashes = HASH_IN_OUTPUT.findall(stdout)
        return len(event_hashes) == 0
