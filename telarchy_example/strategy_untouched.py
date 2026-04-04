"""
Deterministic strategy: untouched markets only, target = current metric total.

When the metric equals the virgin LMSR midpoint, targetValue trades are size zero; optional seed runs
minimal ``higher`` then ``lower`` budget buys (each capped at half of ``MAX_BUDGET_PER_MARKET``), then
a ``targetValue`` nudge spends any remaining budget to pull consensus back to the metric (sequential
one-sided buys slightly unbalance shares, so consensus can sit at e.g. 498.5 until the nudge).

Parity with `agents/trader/scripts/telarchy-untouched-current-value.cjs` except for that seed path.
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


def _virgin_midpoint_equals_target(market: dict[str, Any], target_value: float) -> tuple[bool, float | None]:
    """
    When the API reports consensus=null, the server still uses midpoint (rangeMin+rangeMax)/2 as
    the implicit current value for [0,0] shares (see metrics-tracker betTowardsValue). If the
    metric target equals that within 0.01 credits, the trade size is 0 → HTTP 400 Trade too small.
    """
    if market.get("consensus") is not None:
        return False, None
    try:
        rmin = float(market["rangeMin"])
        rmax = float(market["rangeMax"])
    except (KeyError, TypeError, ValueError):
        return False, None
    mid = rmin + (rmax - rmin) / 2
    if abs(float(target_value) - mid) < 0.01:
        return True, mid
    return False, None


def _minimal_directional_buy(
    client: TelarchyClient,
    market_id: Any,
    direction: str,
    budget_cap: float,
) -> dict[str, Any]:
    """Smallest ``amount`` (credit budget) ≤ ``budget_cap`` that clears Trade too small; doubles on 400."""
    if budget_cap <= 0:
        raise ValueError("budget_cap must be positive")
    b = max(1e-12, min(budget_cap / 1024, budget_cap))
    last_small: TelarchyApiError | None = None
    for _ in range(48):
        try:
            r = client.request(
                "POST",
                "/predictions/trade",
                {
                    "marketId": market_id,
                    "direction": direction,
                    "amount": b,
                },
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
    seed_virgin_midpoint: bool = True,
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
    target_date = str(market.get("targetDate") or "")

    virgin_mid, implied_mid = _virgin_midpoint_equals_target(market, target_value)
    if virgin_mid and implied_mid is not None:
        if dry_run:
            if show_bet:
                cap = max_budget_per_market / 2.0
                print(
                    f"Dry run {mid}: {name} @ {target_date} -> virgin midpoint={implied_mid} "
                    f"equals target={target_value}; would SEED minimal higher+lower "
                    f"(per-leg cap={cap}) then targetValue nudge (remaining budget, SEED_VIRGIN_MIDPOINT)",
                    flush=True,
                )
            return TradeResult(traded=False, skipped=True)
        if not seed_virgin_midpoint:
            if show_bet or _wants_skip_log(verbose, name, log_skip_substrings):
                print(
                    f"Skip {mid}: midpoint={implied_mid} equals target={target_value} "
                    f"(zero targetValue trade); set SEED_VIRGIN_MIDPOINT=1 to open with split higher/lower buy.",
                    flush=True,
                )
            return TradeResult(traded=False, skipped=True)
        leg_cap = max_budget_per_market / 2.0
        res_hi = _minimal_directional_buy(client, mid, "higher", leg_cap)
        time.sleep(0.25)
        res_lo = _minimal_directional_buy(client, mid, "lower", leg_cap)
        c_hi = res_hi.get("cost")
        c_lo = res_lo.get("cost")
        sh_hi = res_hi.get("shares")
        sh_lo = res_lo.get("shares")
        cost_seed = 0.0
        for c in (c_hi, c_lo):
            if isinstance(c, (int, float)):
                cost_seed += float(c)
        consensus_after_seed = res_lo.get("consensus")
        remaining = max_budget_per_market - cost_seed
        res_nudge: dict[str, Any] | None = None
        cons_f: float | None = None
        if isinstance(consensus_after_seed, (int, float)):
            cons_f = float(consensus_after_seed)
        if (
            remaining > 1e-12
            and cons_f is not None
            and abs(cons_f - float(target_value)) > 0.005
        ):
            try:
                res_nudge = client.request(
                    "POST",
                    "/predictions/trade",
                    {
                        "marketId": mid,
                        "targetValue": target_value,
                        "maxBudget": remaining,
                    },
                )
            except TelarchyApiError as e:
                msg = e.body if e.body else str(e)
                if e.status == 400 and "Trade too small" in msg:
                    if show_bet:
                        print(
                            f"Note {mid}: post-seed nudge skipped (Trade too small), "
                            f"consensus_after_seed={cons_f}",
                            file=sys.stderr,
                            flush=True,
                        )
                else:
                    raise
        cost_nudge = 0.0
        consensus_final: Any = consensus_after_seed
        nudge_note = ""
        if isinstance(res_nudge, dict):
            c_n = res_nudge.get("cost")
            if isinstance(c_n, (int, float)):
                cost_nudge = float(c_n)
            consensus_final = res_nudge.get("consensus", consensus_final)
            sh_n = res_nudge.get("shares")
            nudge_note = (
                f" | nudge targetValue maxBudget={remaining} shares={sh_n} cost={c_n} "
                f"-> consensus={consensus_final}"
            )
        cost_sum = cost_seed + cost_nudge
        if show_bet:
            print(
                f"Bet {mid}: {name} @ {target_date} -> SEED minimal higher+lower "
                f"(midpoint deadlock: target={target_value} mid={implied_mid}), "
                f"per_leg_cap={leg_cap}, current={pre_consensus}, liquidity={liq_display}, "
                f"higher shares={sh_hi} cost={c_hi} | lower shares={sh_lo} cost={c_lo} | "
                f"seed_cost={cost_seed} consensus_after_seed={consensus_after_seed}{nudge_note} | "
                f"total_cost={cost_sum}",
                flush=True,
            )
        return TradeResult(traded=True, skipped=False, cost=cost_sum)

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
    seed_virgin_midpoint: bool = True,
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
                seed_virgin_midpoint=seed_virgin_midpoint,
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
