"""
Deterministic strategy: bet on any market the agent has not yet bet on that has liquidity.
Target = current metric total.

When the metric equals the virgin LMSR midpoint, targetValue trades are size zero.
The seed path places minimal higher+lower buys (each capped at MAX_BUDGET/2) to keep
consensus at the midpoint, then a targetValue nudge corrects any residual drift from
sequential one-sided buys (which can leave consensus at e.g. 498.5 instead of 500).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from telarchy_example.client import TelarchyApiError, TelarchyClient
from telarchy_example.pacing import sleep_interruptible
from telarchy_example.metrics import clamp, metric_total

# Thresholds
_VIRGIN_MID_TOL = 0.01        # proximity to midpoint that triggers the seed path
_POST_SEED_DRIFT_TOL = 0.005  # max drift after seed before nudge fires
_MIN_TRADE_BUDGET = 1e-12     # lower bound for minimal directional buy start
_CONSENSUS_MATCH_TOL = 0.01   # consensus within this of target is considered "at value" (matches server's 2-decimal rounding)

def _safe_float(value: Any, default: float | None = None) -> float | None:
    """Convert value to float, returning default for None, bool, and unparseable strings."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _wants_skip_log(verbose: bool, metric_name: str, substrings: tuple[str, ...]) -> bool:
    if verbose:
        return True
    if not substrings:
        return False
    ln = (metric_name or "").lower()
    return any(s in ln for s in substrings)



def _liquidity_positive(liquidity: Any) -> bool:
    f = _safe_float(liquidity)
    return f is not None and f > 0


def _virgin_midpoint_equals_target(market: dict[str, Any], target_value: float) -> tuple[bool, float | None]:
    """
    Return (True, midpoint) when consensus=null and the metric target equals the LMSR midpoint
    within _VIRGIN_MID_TOL. In this state a targetValue trade has zero cost and the API rejects
    it with "Trade too small"; the seed path handles it instead.
    """
    if market.get("consensus") is not None:
        return False, None
    try:
        rmin = float(market["rangeMin"])
        rmax = float(market["rangeMax"])
    except (KeyError, TypeError, ValueError):
        return False, None
    mid = rmin + (rmax - rmin) / 2
    if abs(float(target_value) - mid) < _VIRGIN_MID_TOL:
        return True, mid
    return False, None


def _minimal_directional_buy(
    client: TelarchyClient,
    market_id: Any,
    direction: str,
    budget_cap: float,
) -> dict[str, Any]:
    """
    Find and execute the smallest budget (≤ budget_cap) that clears "Trade too small".

    Starts at budget_cap / 1024 and doubles on each 400 rejection. 48 iterations covers
    2^48 doublings, which far exceeds any practical budget range.
    """
    if budget_cap <= 0:
        raise ValueError("budget_cap must be positive")
    b = max(_MIN_TRADE_BUDGET, min(budget_cap / 1024, budget_cap))
    last_small: TelarchyApiError | None = None
    for _ in range(48):
        try:
            r = client.request(
                "POST",
                "/predictions/trade",
                {"marketId": market_id, "direction": direction, "amount": b},
            )
        except TelarchyApiError as e:
            msg = e.body if e.body else str(e)
            if e.status == 400 and "Trade too small" in msg:
                last_small = e
                if b >= budget_cap - 1e-15:
                    raise
                nb = min(b * 2.0, budget_cap)
                if nb <= b:
                    nb = budget_cap
                b = nb
                time.sleep(0.05)
                continue
            raise
        if isinstance(r, dict):
            return r
        raise TypeError("expected dict from POST /predictions/trade")
    raise RuntimeError("minimal directional buy: iteration limit") from last_small


def _execute_virgin_seed(
    client: TelarchyClient,
    market_id: Any,
    target_value: float,
    max_budget: float,
) -> tuple[float, Any, str]:
    """
    Seed a virgin-midpoint market with paired higher+lower minimal buys to keep consensus
    at the midpoint, then correct any residual drift with a targetValue nudge.

    Returns (total_cost, final_consensus, log_detail_string).
    """
    leg_cap = max_budget / 2.0
    res_hi = _minimal_directional_buy(client, market_id, "higher", leg_cap)
    time.sleep(0.25)
    res_lo = _minimal_directional_buy(client, market_id, "lower", leg_cap)

    c_hi, c_lo = res_hi.get("cost"), res_lo.get("cost")
    sh_hi, sh_lo = res_hi.get("shares"), res_lo.get("shares")
    cost_seed = sum(float(c) for c in (c_hi, c_lo) if isinstance(c, (int, float)))
    consensus_after = res_lo.get("consensus")
    cons_f = _safe_float(consensus_after)

    remaining = max_budget - cost_seed
    res_nudge: dict[str, Any] | None = None
    if remaining > _MIN_TRADE_BUDGET and cons_f is not None and abs(cons_f - target_value) > _POST_SEED_DRIFT_TOL:
        try:
            res_nudge = client.request(
                "POST",
                "/predictions/trade",
                {"marketId": market_id, "targetValue": target_value, "maxBudget": remaining},
            )
        except TelarchyApiError as e:
            msg = e.body if e.body else str(e)
            if e.status == 400 and "Trade too small" in msg:
                print(
                    f"Note {market_id}: post-seed nudge skipped (Trade too small), "
                    f"consensus_after_seed={cons_f}",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                raise

    cost_nudge = 0.0
    consensus_final: Any = consensus_after
    nudge_note = ""
    if isinstance(res_nudge, dict):
        c_n = res_nudge.get("cost")
        if isinstance(c_n, (int, float)):
            cost_nudge = float(c_n)
        consensus_final = res_nudge.get("consensus", consensus_final)
        sh_n = res_nudge.get("shares")
        nudge_note = (
            f" | nudge targetValue maxBudget={remaining} shares={sh_n} "
            f"cost={c_n} -> consensus={consensus_final}"
        )

    detail = (
        f"higher shares={sh_hi} cost={c_hi} | lower shares={sh_lo} cost={c_lo} | "
        f"seed_cost={cost_seed} consensus_after_seed={consensus_after}{nudge_note}"
    )
    return cost_seed + cost_nudge, consensus_final, detail


@dataclass(frozen=True)
class TradingState:
    markets: list[dict[str, Any]]
    metrics_by_id: dict[str, dict[str, Any]]
    balance: float
    agent_position_market_ids: frozenset[str]


@dataclass(frozen=True)
class TradeResult:
    traded: bool
    skipped: bool
    cost: float = 0.0


def load_trading_state(client: TelarchyClient, agent_id: str) -> TradingState:
    markets = client.request("GET", "/predictions/markets?active=true")
    metrics = client.request("GET", "/metrics")
    balance_row = client.request("GET", f"/agents/{agent_id}/balance")
    positions = client.request("GET", "/predictions/positions")
    if not isinstance(markets, list):
        raise TypeError("expected list from GET /predictions/markets?active=true")
    if not isinstance(metrics, list):
        raise TypeError("expected list from GET /metrics")
    if not isinstance(balance_row, dict) or "balance" not in balance_row:
        raise TypeError("expected dict with balance from GET /agents/{id}/balance")
    if not isinstance(positions, list):
        raise TypeError("expected list from GET /predictions/positions")
    by_id = {str(m["id"]): m for m in metrics if isinstance(m, dict) and "id" in m}
    position_market_ids = frozenset(
        str(p["marketId"]) for p in positions if isinstance(p, dict) and "marketId" in p
    )
    return TradingState(
        markets=markets,
        metrics_by_id=by_id,
        balance=float(balance_row["balance"]),
        agent_position_market_ids=position_market_ids,
    )


def execute_trade(
    client: TelarchyClient,
    market: dict[str, Any],
    metrics_by_id: dict[str, dict[str, Any]],
    *,
    agent_position_market_ids: frozenset[str],
    max_budget_per_market: float,
    dry_run: bool,
    verbose: bool = True,
    log_bets: bool | None = None,
    log_skip_substrings: tuple[str, ...] = (),
    seed_virgin_midpoint: bool = True,
    retrade_out_of_consensus: bool = False,
) -> TradeResult:
    show_bet = verbose if log_bets is None else log_bets

    if "id" not in market:
        raise ValueError("market missing id")
    mid = market["id"]
    name = str(market.get("metricName") or "")

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

    if str(mid) in agent_position_market_ids:
        if not retrade_out_of_consensus:
            if _wants_skip_log(verbose, name, log_skip_substrings):
                print(f"Skip {mid}: agent already has a position.", flush=True)
            return TradeResult(traded=False, skipped=True)
        cons_now = _safe_float(market.get("consensus"))
        if cons_now is not None and abs(cons_now - target_value) < _CONSENSUS_MATCH_TOL:
            if _wants_skip_log(verbose, name, log_skip_substrings):
                print(
                    f"Skip {mid}: consensus={cons_now} already at target={target_value}.",
                    flush=True,
                )
            return TradeResult(traded=False, skipped=True)

    pre_consensus = market.get("consensus")
    try:
        liq_display = float(liq)
    except (TypeError, ValueError):
        liq_display = liq
    target_date = str(market.get("targetDate") or "")

    virgin_mid, implied_mid = _virgin_midpoint_equals_target(market, target_value)
    if virgin_mid and implied_mid is not None:
        if dry_run:
            if show_bet:
                cap = max_budget_per_market / 2.0
                print(
                    f"Dry run {mid}: {name} @ {target_date} -> virgin midpoint={implied_mid} "
                    f"equals target={target_value}; would SEED minimal higher+lower "
                    f"(per-leg cap={cap}) then targetValue nudge (SEED_VIRGIN_MIDPOINT)",
                    flush=True,
                )
            return TradeResult(traded=False, skipped=True)
        if not seed_virgin_midpoint:
            if show_bet or _wants_skip_log(verbose, name, log_skip_substrings):
                print(
                    f"Skip {mid}: midpoint={implied_mid} equals target={target_value} "
                    f"(zero targetValue trade); set SEED_VIRGIN_MIDPOINT=1 to enable.",
                    flush=True,
                )
            return TradeResult(traded=False, skipped=True)
        total_cost, _, detail = _execute_virgin_seed(client, mid, target_value, max_budget_per_market)
        if show_bet:
            print(
                f"Bet {mid}: {name} @ {target_date} -> SEED minimal higher+lower "
                f"(midpoint deadlock: target={target_value} mid={implied_mid}), "
                f"per_leg_cap={max_budget_per_market / 2.0}, current={pre_consensus}, "
                f"liquidity={liq_display}, {detail} | total_cost={total_cost}",
                flush=True,
            )
        return TradeResult(traded=True, skipped=False, cost=total_cost)

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
        {"marketId": mid, "targetValue": target_value, "maxBudget": max_budget_per_market},
    )
    if not isinstance(result, dict):
        raise TypeError("expected dict from POST /predictions/trade")

    cost = result.get("cost")
    cons = result.get("consensus")
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
    agent_position_market_ids: frozenset[str],
    max_budget_per_market: float,
    dry_run: bool,
    verbose: bool,
    post_trade_delay_s: float = 0.0,
    rate_limit_backoff_s: float = 65.0,
    should_stop: Callable[[], bool] | None = None,
    log_bets: bool | None = None,
    log_skip_substrings: tuple[str, ...] = (),
    seed_virgin_midpoint: bool = True,
    retrade_out_of_consensus: bool = False,
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
                agent_position_market_ids=agent_position_market_ids,
                max_budget_per_market=max_budget_per_market,
                dry_run=dry_run,
                verbose=verbose,
                log_bets=log_bets,
                log_skip_substrings=log_skip_substrings,
                seed_virgin_midpoint=seed_virgin_midpoint,
                retrade_out_of_consensus=retrade_out_of_consensus,
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
