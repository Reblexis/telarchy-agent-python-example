"""Metric value helpers (parity with FAA Node script)."""

from __future__ import annotations

from typing import Any


def metric_total(metric: dict[str, Any]) -> float:
    mid = metric.get("id", "?")
    total = metric.get("total")
    if isinstance(total, (int, float)):
        return float(total)
    value = metric.get("value")
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError(f"Metric {mid} has no numeric total/value")


def clamp(value: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(max_v, value))
