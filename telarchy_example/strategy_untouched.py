"""
Deterministic strategy: untouched markets only, target = current metric total.

Parity with `agents/trader/scripts/telarchy-untouched-current-value.cjs` in fully-autonomous-agents.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from telarchy_example.client import TelarchyApiError, TelarchyClient
from telarchy_example.pacing import sleep_interruptible
from telarchy_example.metrics import clamp, metric_total


def _wants_skip_log(verbose: bool, metric_name: str, substrings: tuple[str, ...]) -> bool:
    if verbose:
        return True
    if not substrings:
        return False
    ln = (metric_name or "").lower()
    return any(s in ln for s in substrings)


def _trade_count_is_zero(trade_count: Any) -> bool:
    if trade_count is None:
        return True
    try:
        return int(float(trade_count)) == 0
    except (TypeError, ValueError):
        return False


def _liquidity_positive(liquidity: Any) -> bool:
    try:
        return float(liquidity) > 0
    except (TypeError, ValueError):
        return False


def _consensus_matches_target(consensus: Any, target: float) -> bool:
    if consensus is None:
        return False
    if isinstance(consensus, bool):
        return False
    if isinstance(consensus, (int, float)):
        return abs(float(consensus) - target) < 1e-9
    if isinstance(consensus, str) and consensus.strip():
        try:
            return abs(float(consensus) - target) < 1e-9
        except ValueError:
            return False
    return False


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
    verbose: bool = True,
    log_bets: bool | None = None,
    log_skip_substrings: tuple[str, ...] = (),
) -> TradeResult:
    show_bet = verbose if log_bets is None else log_bets

    if "id" not in market:
        raise ValueError("market missing id")
    mid = market["id"]
    name = str(market.get("metricName") or "")
    trade_count = market.get("tradeCount")
    if not _trade_count_is_zero(trade_count):
        if _wants_skip_log(verbose, name, log_skip_substrings):
            print(f"Skip {mid}: already traded ({trade_count}).", flush=True)
        return TradeResult(traded=False, skipped=True)

    liq = market.get("liquidity")
    if not _liquidity_positive(liq):
        if _wants_skip_log(verbose, name, log_skip_substrings):
            print(f"Skip {mid}: no liquidity (liquidity={liq!r}).", flush=True)
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
    if _consensus_matches_target(consensus, target_value):
        if _wants_skip_log(verbose, name, log_skip_substrings):
            print(
                f"Skip {mid}: consensus already at target {target_value} (current={consensus!r}).",
                flush=True,
            )
        return TradeResult(traded=False, skipped=True)

    pre_consensus = market.get("consensus")
    try:
        liq_display = float(liq)
    except (TypeError, ValueError):
        liq_display = liq

    if dry_run:
        if show_bet:
            print(
                f"Dry run {mid}: {name} -> target={target_value}, "
                f"maxBudget={max_budget_per_market}, "
                f"current={pre_consensus}, liquidity={liq_display}",
                flush=True,
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
    if show_bet:
        print(
            f"Bet {mid}: {name} @ {target_date} -> target={target_value}, "
            f"current={pre_consensus}, liquidity={liq_display}, "
            f"cost={cost}, consensus={cons}",
            flush=True,
        )
    traded_cost = float(cost) if isinstance(cost, (int, float)) else 0.0
    return TradeResult(traded=True, skipped=False, cost=traded_cost)


def run_untouched_on_markets(
    client: TelarchyClient,
    markets: list[dict[str, Any]],
    metrics_by_id: dict[str, dict[str, Any]],
    *,
    max_budget_per_market: float,
    dry_run: bool,
    verbose: bool,
    post_trade_delay_s: float = 0.0,
    rate_limit_backoff_s: float = 65.0,
    should_stop: Callable[[], bool] | None = None,
    log_bets: bool | None = None,
    log_skip_substrings: tuple[str, ...] = (),
) -> int:
    """Returns number of markets where a trade was placed (not dry-run skips)."""
    traded_count = 0
    for market in markets:
        if should_stop is not None and should_stop():
            break
        if not isinstance(market, dict):
            continue
        mid = market.get("id", "?")
        mname = str(market.get("metricName") or "")
        try:
            result = execute_trade(
                client,
                market,
                metrics_by_id,
                max_budget_per_market=max_budget_per_market,
                dry_run=dry_run,
                verbose=verbose,
                log_bets=log_bets,
                log_skip_substrings=log_skip_substrings,
            )
            if result.traded:
                traded_count += 1
                if sleep_interruptible(post_trade_delay_s, should_stop):
                    return traded_count
        except (TypeError, ValueError) as e:
            print(f"Skip {mid} ({mname}): {e}", file=sys.stderr, flush=True)
            continue
        except TelarchyApiError as e:
            msg = e.body if e.body else str(e)
            if e.status == 429:
                if verbose:
                    print(
                        f"Rate limited on {mid}; sleeping {rate_limit_backoff_s:.0f}s",
                        file=sys.stderr,
                    )
                if sleep_interruptible(rate_limit_backoff_s, should_stop):
                    return traded_count
                continue
            if e.status == 400 and "Trade too small" in msg:
                if _wants_skip_log(verbose, mname, log_skip_substrings):
                    print(
                        f"Skip {mid}: trade too small (try raising MAX_BUDGET_PER_MARKET).",
                        file=sys.stderr,
                        flush=True,
                    )
                if sleep_interruptible(post_trade_delay_s, should_stop):
                    return traded_count
                continue
            if "Insufficient balance" in msg:
                print("Stopping: insufficient balance.", file=sys.stderr)
                break
            print(f"Failed on {mid}: {e}", file=sys.stderr)
            if sleep_interruptible(post_trade_delay_s, should_stop):
                return traded_count
    return traded_count
