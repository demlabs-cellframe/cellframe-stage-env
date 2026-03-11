"""Schema models for metric collection and display steps."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MetricStep(BaseModel):
    """
    Record a named metric value.

    Usage:
      - metric: throughput_http
        value: "{{throughput_value}}"
        unit: Mbps
        group: transport_benchmark
        tags:
          transport: http
          baseline: true
    """
    metric: str = Field(..., description="Metric name (unique within group)")
    value: Any = Field(..., description="Metric value (number or string, supports {{var}} substitution)")
    unit: Optional[str] = Field(None, description="Unit of measurement (Mbps, ms, %, etc.)")
    group: str = Field("default", description="Group name for organizing metrics")
    tags: Optional[Dict[str, Any]] = Field(None, description="Arbitrary key-value tags for the metric")


class MetricsTableStep(BaseModel):
    """
    Render collected metrics as a formatted table.

    Usage:
      - metrics_table: transport_benchmark
        title: "Transport Benchmark Results"
        columns:
          - name
          - value
          - unit

      With tag columns:
      - metrics_table: transport_benchmark
        title: "Results"
        columns:
          - tag:transport
          - value
          - unit
          - tag:overhead
    """
    metrics_table: str = Field(..., description="Metric group name to display")
    title: Optional[str] = Field(None, description="Table title")
    columns: Optional[List[str]] = Field(
        None,
        description=(
            "Columns to show. Built-in: 'name', 'value', 'unit'. "
            "Prefix 'tag:' for tag values (e.g. 'tag:transport'). "
            "If omitted, shows name/value/unit."
        ),
    )
    format: str = Field("text", description="Output format: text (console) or markdown")
