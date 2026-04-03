"""
Deterministic strategy: untouched markets only, target = current metric total.

Parity with `agents/trader/scripts/telarchy-untouched-current-value.cjs` in fully-autonomous-agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from telarchy_example.client import TelarchyClient
from telarchy_example.metrics import clamp, metric_total


@dataclass(frozen=True)
class TradingState:
    markets: list[dict[str, Any]]
    metrics_by_id: dict[str, dict[str, Any]]
    balance: float


@dataclass(frozen=True)
class TradeResult:
    traded: bool
    skipped: bool
    cost: float = 0.0


def load_trading_state(client: TelarchyClient, agent_id: str) -> TradingState:
    markets = client.request("GET", "/predictions/markets?active=true")
    metrics = client.request("GET", "/metrics")
    balance_row = client.request("GET", f"/agents/{agent_id}/balance")
    if not isinstance(markets, list):
        raise TypeError("expected list from GET /predictions/markets?active=true")
    if not isinstance(metrics, list):
        raise TypeError("expected list from GET /metrics")
    if not isinstance(balance_row, dict) or "balance" not in balance_row:
        raise TypeError("expected dict with balance from GET /agents/{id}/balance")
    by_id = {str(m["id"]): m for m in metrics if isinstance(m, dict) and "id" in m}
    return TradingState(
        markets=markets,
        metrics_by_id=by_id,
        balance=float(balance_row["balance"]),
    )


def execute_trade(
    client: TelarchyClient,
    market: dict[str, Any],
    metrics_by_id: dict[str, dict[str, Any]],
    *,
    max_budget_per_market: float,
    dry_run: bool,
) -> TradeResult:
    if "id" not in market:
        raise ValueError("market missing id")
    mid = market["id"]
    trade_count = market.get("tradeCount")
    if trade_count != 0:
        print(f"Skip {mid}: already traded ({trade_count}).")
        return TradeResult(traded=False, skipped=True)

    liq = market.get("liquidity")
    if not (isinstance(liq, (int, float)) and liq > 0):
        print(f"Skip {mid}: no liquidity.")
        return TradeResult(traded=False, skipped=True)

    metric_id = market.get("metricId")
    metric = metrics_by_id.get(str(metric_id)) if metric_id is not None else None
    if metric is None:
        raise ValueError(f"Metric {metric_id} not found for market {mid}")

    target_value = clamp(
        metric_total(metric),
        float(market["rangeMin"]),
        float(market["rangeMax"]),
    )
    consensus = market.get("consensus")
    if isinstance(consensus, (int, float)) and abs(float(consensus) - target_value) < 1e-9:
        print(f"Skip {mid}: consensus already at target {target_value}.")
        return TradeResult(traded=False, skipped=True)

    name = market.get("metricName", "")
    if dry_run:
        print(
            f"Dry run {mid}: {name} -> target={target_value}, "
            f"maxBudget={max_budget_per_market}",
        )
        return TradeResult(traded=False, skipped=True)

    result = client.request(
        "POST",
        "/predictions/trade",
        {
            "marketId": mid,
            "targetValue": target_value,
            "maxBudget": max_budget_per_market,
        },
    )
    if not isinstance(result, dict):
        raise TypeError("expected dict from POST /predictions/trade")

    cost = result.get("cost")
    cons = result.get("consensus")
    target_date = market.get("targetDate", "")
    print(
        f"Bet {mid}: {name} @ {target_date} -> target={target_value}, "
        f"cost={cost}, consensus={cons}",
    )
    traded_cost = float(cost) if isinstance(cost, (int, float)) else 0.0
    return TradeResult(traded=True, skipped=False, cost=traded_cost)
