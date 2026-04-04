"""One-shot CLI: `--all` / `--market`, optional `--dry-run` (overrides DRY_RUN env)."""

from __future__ import annotations

import argparse
import sys
from typing import Any, Sequence

from telarchy_example.client import TelarchyClient, TelarchyApiError
from telarchy_example.config import load_agent_runtime
from telarchy_example.strategy_untouched import load_trading_state, run_untouched_on_markets


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Telarchy untouched-current-value: seed untouched markets toward current metric values.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Consider all active markets")
    group.add_argument("--market", metavar="MARKET_ID", help="Single market id")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without POST /predictions/trade (overrides DRY_RUN in .env)",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Force live trades even if DRY_RUN=1 in .env",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    rt = load_agent_runtime()

    if args.dry_run and args.no_dry_run:
        print("Fatal: use only one of --dry-run and --no-dry-run", file=sys.stderr)
        raise SystemExit(1)

    dry_run = rt.dry_run
    if args.dry_run:
        dry_run = True
    if args.no_dry_run:
        dry_run = False

    client = TelarchyClient(
        rt.telarchy_url,
        rt.api_key,
        rt.workspace_id,
    )
    try:
        state = load_trading_state(client, rt.agent_id)

        if args.all:
            selected: list[dict[str, Any]] = state.markets
        else:
            assert args.market is not None
            selected = [m for m in state.markets if str(m.get("id")) == str(args.market)]

        if not args.all and not selected:
            print(f"Market {args.market} not found among active markets.")
            return

        post_delay = 0.0 if dry_run else rt.trade_post_delay_seconds
        traded_count = run_untouched_on_markets(
            client,
            selected,
            state.metrics_by_id,
            max_budget_per_market=rt.max_budget_per_market,
            dry_run=dry_run,
            verbose=True,
            post_trade_delay_s=post_delay,
            rate_limit_backoff_s=rt.trade_rate_limit_backoff_seconds,
            log_skip_substrings=rt.log_skip_metric_substrings,
            seed_virgin_midpoint=rt.seed_virgin_midpoint,
        )

        print("Dry run complete." if dry_run else f"Placed {traded_count} trade(s).")
    finally:
        client.close()


def entrypoint() -> None:
    try:
        main()
    except (ValueError, TelarchyApiError, OSError, RuntimeError, TypeError) as e:
        print(f"Fatal: {e}", file=sys.stderr)
        raise SystemExit(1) from e


if __name__ == "__main__":
    entrypoint()
