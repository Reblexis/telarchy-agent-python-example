"""CLI: untouched-current-value strategy (`--all` / `--market`, optional `--dry-run`)."""

from __future__ import annotations

import argparse
import sys
from typing import Any, Sequence

from telarchy_example.client import TelarchyClient, TelarchyApiError
from telarchy_example.config import load_config, read_api_key
from telarchy_example.strategy_untouched import execute_trade, load_trading_state


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
        help="Print actions without POST /predictions/trade",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    cfg = load_config()
    api_key = read_api_key(cfg.key_file)

    client = TelarchyClient(
        cfg.telarchy_url,
        api_key,
        cfg.workspace_id,
    )
    try:
        state = load_trading_state(client, cfg.agent_id)

        if args.all:
            selected: list[dict[str, Any]] = state.markets
        else:
            assert args.market is not None
            selected = [m for m in state.markets if str(m.get("id")) == str(args.market)]

        if not args.all and not selected:
            print(f"Market {args.market} not found among active markets.")
            return

        traded_count = 0
        for market in selected:
            if not isinstance(market, dict):
                continue
            try:
                result = execute_trade(
                    client,
                    market,
                    state.metrics_by_id,
                    max_budget_per_market=cfg.max_budget_per_market,
                    dry_run=args.dry_run,
                )
                if result.traded:
                    traded_count += 1
            except Exception as e:
                message = str(e)
                if "Insufficient balance" in message:
                    print("Stopping: insufficient balance.")
                    break
                mid = market.get("id", "?")
                print(f"Failed on {mid}: {message}", file=sys.stderr)

        print("Dry run complete." if args.dry_run else f"Placed {traded_count} trade(s).")
    finally:
        client.close()


def entrypoint() -> None:
    try:
        main()
    except (ValueError, TelarchyApiError, OSError) as e:
        print(f"Fatal: {e}", file=sys.stderr)
        raise SystemExit(1) from e


if __name__ == "__main__":
    entrypoint()
