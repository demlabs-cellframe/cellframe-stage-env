"""Executors for metric collection and display steps."""

import time
from typing import Any, Dict, List

from ...utils.logger import get_logger
from .base import StepExecutor
from ..schema_metrics import MetricStep, MetricsTableStep
from ..executor import RuntimeContext

logger = get_logger(__name__)


class MetricStepExecutor(StepExecutor):
    """Records a named metric value into the runtime context."""

    async def execute(self, step: MetricStep, ctx: RuntimeContext) -> None:
        name = ctx.substitute(str(step.metric))
        raw_value = ctx.substitute(str(step.value))
        group = ctx.substitute(step.group)
        unit = ctx.substitute(step.unit) if step.unit else None

        try:
            value = float(raw_value)
        except (ValueError, TypeError):
            value = raw_value

        tags = {}
        if step.tags:
            tags = {k: ctx.substitute(str(v)) for k, v in step.tags.items()}

        entry = {
            "name": name,
            "value": value,
            "unit": unit,
            "group": group,
            "tags": tags,
            "timestamp": time.time(),
        }

        ctx.add_metric(entry)

        logger.info("metric_recorded", name=name, value=value, unit=unit, group=group)
        ctx.add_result("metric", True, {"name": name, "value": value, "unit": unit, "group": group})


class MetricsTableStepExecutor(StepExecutor):
    """Renders collected metrics for a group as a formatted table."""

    async def execute(self, step: MetricsTableStep, ctx: RuntimeContext) -> None:
        group = ctx.substitute(step.metrics_table)
        title = ctx.substitute(step.title) if step.title else f"Metrics: {group}"
        fmt = step.format or "text"

        metrics = [m for m in ctx.get_metrics() if m.get("group") == group]
        if not metrics:
            msg = f"[{title}] No metrics collected for group '{group}'"
            print(msg)
            logger.warning("metrics_table_empty", group=group)
            ctx.add_result("metrics_table", True, {"group": group, "count": 0})
            return

        columns = step.columns or ["name", "value", "unit"]

        header, rows = self._build_table(metrics, columns)

        output = self._render(title, header, rows, fmt)
        print(output)

        ctx.add_result("metrics_table", True, {
            "group": group, "count": len(metrics), "output": output,
        })

    @staticmethod
    def _cell(metric: Dict[str, Any], col: str) -> str:
        if col.startswith("tag:"):
            tag_key = col[4:]
            return str(metric.get("tags", {}).get(tag_key, ""))
        raw = metric.get(col, "")
        if isinstance(raw, float):
            return f"{raw:.4g}"
        return str(raw) if raw is not None else ""

    def _build_table(
        self, metrics: List[Dict], columns: List[str]
    ) -> tuple:
        header = []
        for col in columns:
            if col.startswith("tag:"):
                header.append(col[4:])
            else:
                header.append(col.capitalize())

        rows = []
        for m in metrics:
            rows.append([self._cell(m, col) for col in columns])

        return header, rows

    @staticmethod
    def _render(title: str, header: List[str], rows: List[List[str]], fmt: str) -> str:
        widths = [len(h) for h in header]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))

        lines = [f"\n=== {title} ==="]

        if fmt == "markdown":
            hdr = "| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(header)) + " |"
            sep = "| " + " | ".join("-" * widths[i] for i in range(len(header))) + " |"
            lines.append(hdr)
            lines.append(sep)
            for row in rows:
                lines.append("| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(row)) + " |")
        else:
            hdr = "  ".join(h.ljust(widths[i]) for i, h in enumerate(header))
            lines.append(hdr)
            lines.append("-" * len(hdr))
            for row in rows:
                lines.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)))

        lines.append("")
        return "\n".join(lines)
