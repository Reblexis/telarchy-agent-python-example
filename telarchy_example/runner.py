"""Long-running agent: auto-register, then poll and trade on viable markets."""

from __future__ import annotations

import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from telarchy_example.client import TelarchyClient, TelarchyApiError
from telarchy_example.config import load_agent_runtime
from telarchy_example.pacing import sleep_interruptible
from telarchy_example.strategy_untouched import load_trading_state, run_untouched_on_markets


def main() -> None:
    stop = threading.Event()

    def handle_stop(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)

    base = Path.cwd()
    rt = load_agent_runtime(base)
    client = TelarchyClient(rt.telarchy_url, rt.api_key, rt.workspace_id)

    mode = "dry-run" if rt.dry_run else "live"
    post_delay = 0.0 if rt.dry_run else rt.trade_post_delay_seconds
    pacing_note = (
        f" | pacing={post_delay:g}s/trade | 429_backoff={rt.trade_rate_limit_backoff_seconds:g}s"
        if post_delay > 0
        else ""
    )
    print(
        f"Telarchy agent {rt.agent_id} | {rt.telarchy_url} | "
        f"workspace={rt.workspace_id!r} | poll={rt.poll_interval_seconds:g}s{pacing_note} | {mode}\n"
        f"  (each poll: GET markets/metrics/balance once, then one pass over markets; "
        f"Ctrl+C stops within ~0.25s)",
        flush=True,
    )

    try:
        while not stop.is_set():
            try:
                state = load_trading_state(client, rt.agent_id)
                traded = run_untouched_on_markets(
                    client,
                    state.markets,
                    state.metrics_by_id,
                    max_budget_per_market=rt.max_budget_per_market,
                    dry_run=rt.dry_run,
                    verbose=False,
                    log_bets=True,
                    post_trade_delay_s=post_delay,
                    rate_limit_backoff_s=rt.trade_rate_limit_backoff_seconds,
                    should_stop=stop.is_set,
                )
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                print(
                    f"[{ts}] markets={len(state.markets)} balance={state.balance} "
                    f"placed={traded}" + (" (dry-run)" if rt.dry_run else ""),
                    flush=True,
                )
            except TelarchyApiError as e:
                print(f"[error] API: {e}", file=sys.stderr, flush=True)
            except (OSError, RuntimeError, TypeError, ValueError) as e:
                print(f"[error] {e}", file=sys.stderr, flush=True)

            if stop.is_set():
                break
            sleep_interruptible(rt.poll_interval_seconds, stop.is_set)
    finally:
        client.close()
        print("Stopped.", flush=True)


def entrypoint() -> None:
    try:
        main()
    except (ValueError, OSError, RuntimeError) as e:
        print(f"Fatal: {e}", file=sys.stderr)
        raise SystemExit(1) from e


if __name__ == "__main__":
    entrypoint()
