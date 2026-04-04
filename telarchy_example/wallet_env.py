"""Resolve EVM funding key from env or an OpenClaw-style .env with WALLET_SEED_PHRASE."""

from __future__ import annotations

import os
import re
from pathlib import Path

# Matches FAA `send-usdc.js`: m/44'/60'/0'/0/0
EVM_DEFAULT_PATH = "m/44'/60'/0'/0/0"


def _parse_seed_line(text: str) -> str | None:
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(
            r'^WALLET_SEED_PHRASE\s*=\s*(.+)$',
            line,
        )
        if not m:
            continue
        val = m.group(1).strip().strip("'\"")
        return val or None
    return None


def read_mnemonic_from_file(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"wallet env file not found: {path}")
    phrase = _parse_seed_line(path.read_text(encoding="utf-8"))
    if not phrase:
        raise ValueError(f"WALLET_SEED_PHRASE not found in {path}")
    return phrase


def resolve_evm_private_key_and_address() -> tuple[str, str]:
    """
    Returns (private_key_hex_with_0x, checksummed_address).

    Order:
    1. EVM_PRIVATE_KEY (+ optional EVM_ADDRESS check)
    2. TELARCHY_AGENT_WALLET_ENV — path to .env containing WALLET_SEED_PHRASE (OpenClaw workspace)
    3. WALLET_SEED_PHRASE_FILE — path to file containing only the mnemonic or KEY=value lines
    """
    pk = os.environ.get("EVM_PRIVATE_KEY", "").strip()
    if pk:
        from web3 import Web3
        from eth_account import Account

        acct = Account.from_key(pk if pk.startswith("0x") else "0x" + pk)
        addr = Web3.to_checksum_address(acct.address)
        env_addr = os.environ.get("EVM_ADDRESS", "").strip()
        if env_addr:
            expected = Web3.to_checksum_address(env_addr)
            if expected != addr:
                raise ValueError(f"EVM_ADDRESS {expected} does not match EVM_PRIVATE_KEY ({addr})")
        return (pk if pk.startswith("0x") else "0x" + pk), addr

    env_file = os.environ.get("TELARCHY_AGENT_WALLET_ENV", "").strip()
    seed_file = os.environ.get("WALLET_SEED_PHRASE_FILE", "").strip()
    path: Path | None = None
    if env_file:
        path = Path(env_file).expanduser()
    elif seed_file:
        path = Path(seed_file).expanduser()

    if path is None:
        raise ValueError(
            "Set EVM_PRIVATE_KEY, or TELARCHY_AGENT_WALLET_ENV (OpenClaw .env path), "
            "or WALLET_SEED_PHRASE_FILE",
        )

    mnemonic = read_mnemonic_from_file(path)
    return _mnemonic_to_key_and_address(mnemonic)


def _mnemonic_to_key_and_address(mnemonic: str) -> tuple[str, str]:
    from eth_account import Account
    from web3 import Web3

    Account.enable_unaudited_hdwallet_features()
    acct = Account.from_mnemonic(mnemonic.strip(), account_path=EVM_DEFAULT_PATH)
    pk = acct.key.hex()
    if not pk.startswith("0x"):
        pk = "0x" + pk
    return pk, Web3.to_checksum_address(acct.address)


def resolve_funding_wallet_address() -> str | None:
    """
    Same on-chain address as `telarchy-fund` (EVM_ADDRESS overrides derived key).

    Returns None if no EVM_PRIVATE_KEY / TELARCHY_AGENT_WALLET_ENV / WALLET_SEED_PHRASE_FILE.
    """
    try:
        _, derived = resolve_evm_private_key_and_address()
    except ValueError:
        return None
    from web3 import Web3

    env_addr = os.environ.get("EVM_ADDRESS", "").strip()
    if env_addr:
        return Web3.to_checksum_address(env_addr)
    return derived
