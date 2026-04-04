"""
Buy Telarchy credits by sending USDC on Base to the server treasury, then POST /agents/:id/deposit.

Matches server formula: credits = floor(usdc / (creditValueUsd * (1 + buyFeePercent/100))).
"""

from __future__ import annotations

import os
from decimal import Decimal, ROUND_UP
from typing import Any

import httpx
from web3 import Web3
from web3.contract import Contract

from telarchy_example.client import TelarchyClient, TelarchyApiError

ERC20_MIN_ABI: list[dict[str, Any]] = [
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
]

USDC_DECIMALS = 6


def fetch_deposit_address(telarchy_url: str) -> dict[str, Any]:
    """GET /agents/deposit-address (no auth)."""
    base = telarchy_url.rstrip("/")
    url = f"{base}/agents/deposit-address"
    resp = httpx.get(url, timeout=30.0)
    if resp.status_code == 503:
        raise RuntimeError(
            "Treasury is not configured on this server (503 from /agents/deposit-address). "
            "USDC purchase is unavailable for this host.",
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"GET /agents/deposit-address -> {resp.status_code}: {resp.text}")
    data = resp.json()
    if not isinstance(data, dict) or "address" not in data:
        raise ValueError(f"unexpected deposit-address response: {data!r}")
    return data


def _credit_value_usd_from_status(client: TelarchyClient) -> float:
    st = client.request("GET", "/status")
    if not isinstance(st, dict):
        raise TypeError("GET /status did not return a JSON object")
    cv = st.get("creditValueUsd")
    if cv is None:
        raise ValueError(
            "Server returned creditValueUsd=null on GET /status; configure economy or use admin credit.",
        )
    return float(cv)


def usdc_amount_for_credits(
    target_credits: int,
    credit_value_usd: float,
    buy_fee_percent: float,
) -> Decimal:
    if target_credits < 1:
        raise ValueError("target_credits must be at least 1")
    buy_rate = Decimal(str(credit_value_usd)) * (
        Decimal("1") + Decimal(str(buy_fee_percent)) / Decimal("100")
    )
    raw = Decimal(target_credits) * buy_rate
    return raw.quantize(Decimal("1") / Decimal(10**USDC_DECIMALS), rounding=ROUND_UP)


def purchase_credits_with_usdc(
    client: TelarchyClient,
    telarchy_url: str,
    agent_id: str,
    target_credits: int,
    *,
    evm_private_key: str,
    evm_address: str | None,
    rpc_url: str,
    chain_id: int,
    buy_fee_percent: float,
    receipt_timeout_s: float = 600.0,
) -> dict[str, Any]:
    """
    Send USDC to treasury on Base, wait for confirmation, then notify the Telarchy API.

    `evm_address` if set must match the address derived from `evm_private_key`.
    """
    pk = evm_private_key.strip()
    if pk.startswith("0x"):
        pk = pk[2:]

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        raise RuntimeError(f"Could not connect to RPC: {rpc_url}")

    acct = w3.eth.account.from_key("0x" + pk)
    derived = Web3.to_checksum_address(acct.address)
    if evm_address:
        expected = Web3.to_checksum_address(evm_address.strip())
        if expected != derived:
            raise ValueError(
                f"EVM_ADDRESS {expected} does not match private key address {derived}",
            )

    dep = fetch_deposit_address(telarchy_url)
    treasury = Web3.to_checksum_address(str(dep["address"]))
    usdc_addr = Web3.to_checksum_address(str(dep["usdcContract"]))

    credit_value_usd = _credit_value_usd_from_status(client)
    usdc_decimal = usdc_amount_for_credits(
        target_credits,
        credit_value_usd,
        buy_fee_percent,
    )
    amount_raw = int(usdc_decimal * (10**USDC_DECIMALS))

    contract: Contract = w3.eth.contract(address=usdc_addr, abi=ERC20_MIN_ABI)

    bal = contract.functions.balanceOf(derived).call()
    if bal < amount_raw:
        need = usdc_decimal
        have = Decimal(bal) / Decimal(10**USDC_DECIMALS)
        raise RuntimeError(
            f"Insufficient USDC on Base: need {need} USDC, have {have} USDC at {derived}",
        )

    nonce = w3.eth.get_transaction_count(derived, "pending")
    latest = w3.eth.get_block("latest")
    base_fee = latest["baseFeePerGas"]
    priority = Web3.to_wei(0.05, "gwei")
    max_fee = base_fee * 2 + priority

    tx = contract.functions.transfer(treasury, amount_raw).build_transaction(
        {
            "from": derived,
            "nonce": nonce,
            "chainId": chain_id,
            "type": 2,
            "maxPriorityFeePerGas": priority,
            "maxFeePerGas": max_fee,
        },
    )
    gas_est = contract.functions.transfer(treasury, amount_raw).estimate_gas({"from": derived})
    tx["gas"] = int(gas_est * 1.2) + 10_000

    signed = w3.eth.account.sign_transaction(tx, private_key="0x" + pk)
    raw = signed.raw_transaction
    tx_hash = w3.eth.send_raw_transaction(raw)
    hx = tx_hash.hex() if hasattr(tx_hash, "hex") else Web3.to_hex(tx_hash)
    if not hx.startswith("0x"):
        hx = "0x" + hx

    print(
        f"Sent {usdc_decimal} USDC to treasury {treasury}; tx {hx} (waiting for receipt…)",
        flush=True,
    )
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=receipt_timeout_s)
    if receipt.get("status") != 1:
        raise RuntimeError(f"USDC transfer failed on-chain (status != 1): {hx}")

    try:
        result = client.request(
            "POST",
            f"/agents/{agent_id}/deposit",
            {"txHash": hx},
        )
    except TelarchyApiError as e:
        if e.status == 409:
            raise RuntimeError(
                f"Deposit rejected (tx may already be used): {e}",
            ) from e
        raise

    if not isinstance(result, dict):
        raise TypeError(f"unexpected deposit response: {result!r}")
    return result
