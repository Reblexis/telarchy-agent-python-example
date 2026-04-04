"""Fresh agent credits (API) and Base wallet ETH / USDC (on-chain)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from web3 import Web3
from web3.contract import Contract

from telarchy_example.client import TelarchyClient
from telarchy_example.usdc_deposit import ERC20_MIN_ABI, USDC_DECIMALS, fetch_deposit_address


def fetch_agent_credits(client: TelarchyClient, agent_id: str) -> float:
    row = client.request("GET", f"/agents/{agent_id}/balance")
    if not isinstance(row, dict) or "balance" not in row:
        raise TypeError("expected dict with balance from GET /agents/{id}/balance")
    return float(row["balance"])


def read_base_wallet_balances(
    telarchy_url: str,
    rpc_url: str,
    wallet_address: str,
) -> dict[str, float | None]:
    """
    Native ETH and USDC (from GET /agents/deposit-address ``usdcContract``) on Base.

    ``usdc`` is None if treasury/USDC metadata is unavailable (e.g. 503).
    """
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise RuntimeError(f"could not connect to RPC: {rpc_url}")

    addr = Web3.to_checksum_address(wallet_address)
    wei = int(w3.eth.get_balance(addr))
    eth = float(w3.from_wei(wei, "ether"))

    usdc: float | None = None
    try:
        dep: dict[str, Any] = fetch_deposit_address(telarchy_url)
        usdc_addr = Web3.to_checksum_address(str(dep["usdcContract"]))
        contract: Contract = w3.eth.contract(address=usdc_addr, abi=ERC20_MIN_ABI)
        raw = int(contract.functions.balanceOf(addr).call())
        usdc = float(Decimal(raw) / Decimal(10**USDC_DECIMALS))
    except (RuntimeError, ValueError, KeyError, TypeError, OSError):
        usdc = None

    return {"eth": eth, "usdc": usdc}
