"""CLI: send USDC on Base to treasury, then POST /agents/:id/deposit."""

from __future__ import annotations

import argparse
import os
import sys

from telarchy_example.client import TelarchyApiError, TelarchyClient
from telarchy_example.config import load_agent_runtime
from telarchy_example.usdc_deposit import purchase_credits_with_usdc
from telarchy_example.wallet_env import resolve_evm_private_key_and_address


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Buy Telarchy credits with USDC (Base). Sends USDC to treasury from GET /agents/deposit-address, then submits tx hash to the API.",
        epilog="Example: telarchy-fund 50",
    )
    parser.add_argument(
        "credits_pos",
        nargs="?",
        type=int,
        metavar="CREDITS",
        help="How many credits to buy (minimum target; USDC amount follows server GET /status creditValueUsd). Preferred over --credits and CREDITS_TO_PURCHASE.",
    )
    parser.add_argument(
        "--credits",
        "-c",
        type=int,
        default=None,
        metavar="N",
        dest="credits_flag",
        help="Same as positional CREDITS (optional if you pass the number first).",
    )
    args = parser.parse_args(argv)

    if args.credits_pos is not None and args.credits_flag is not None:
        print(
            "Fatal: use either positional CREDITS or --credits, not both",
            file=sys.stderr,
        )
        raise SystemExit(1)

    rt = load_agent_runtime()

    if args.credits_pos is not None:
        credits = args.credits_pos
    elif args.credits_flag is not None:
        credits = args.credits_flag
    else:
        raw = os.environ.get("CREDITS_TO_PURCHASE", "").strip()
        if not raw:
            print(
                "Fatal: pass how many credits to buy, e.g.  telarchy-fund 50",
                file=sys.stderr,
            )
            raise SystemExit(1)
        credits = int(raw)

    pk, derived_addr = resolve_evm_private_key_and_address()
    addr = (os.environ.get("EVM_ADDRESS", "").strip() or derived_addr)
    rpc = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org").strip()
    chain_id = int(os.environ.get("BASE_CHAIN_ID", "8453"))
    fee_pct = float(os.environ.get("DEPOSIT_BUY_FEE_PERCENT", "0"))

    client = TelarchyClient(rt.telarchy_url, rt.api_key, rt.workspace_id)
    try:
        out = purchase_credits_with_usdc(
            client,
            rt.telarchy_url,
            rt.agent_id,
            credits,
            evm_private_key=pk,
            evm_address=addr,
            rpc_url=rpc,
            chain_id=chain_id,
            buy_fee_percent=fee_pct,
        )
        print(out)
    finally:
        client.close()


def entrypoint() -> None:
    try:
        main()
    except (ValueError, OSError, RuntimeError, TelarchyApiError, TypeError) as e:
        print(f"Fatal: {e}", file=sys.stderr)
        raise SystemExit(1) from e


if __name__ == "__main__":
    entrypoint()
