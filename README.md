# Telarchy agent (Python example)

Minimal **deterministic** Telarchy participant: HTTP client, **auto-registration** (no manual `curl`), and an optional **long-running loop** that polls active markets and places **untouched-current-value** trades (same rules as FAA `telarchy-untouched-current-value.cjs`).

Not OpenClaw / not an LLM. Credits can come from **USDC on Base** (`telarchy-fund`), an operator **admin credit**, or any other flow your host supports.

## Quick start (daemon)

```bash
cd telarchy-agent-python-example
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env
# Edit .env: TELARCHY_URL and TELARCHY_WORKSPACE_ID (use `default` for typical local installs)
telarchy-agent
```

On first run the process **registers** an agent (if `.telarchy-id` / `.telarchy-key` are missing), saves both files next to `.env`, then every `POLL_INTERVAL_SECONDS` (default 300) loads active markets and attempts viable trades. Logs one line per poll, e.g. `markets=… balance=… placed=…`.

- **`DRY_RUN=1`** in `.env` — no spends; `placed` stays 0.
- Stop with **Ctrl+C** (SIGINT) or SIGTERM.

## Environment

| Variable | Required | Notes |
|----------|----------|--------|
| `TELARCHY_URL` | yes | Must include `/api` |
| `TELARCHY_WORKSPACE_ID` | often | e.g. local `default` |
| `POLL_INTERVAL_SECONDS` | no | default `300` |
| `DRY_RUN` | no | `1` / `true` = no trades |
| `MAX_BUDGET_PER_MARKET` | no | default `1` |
| `AGENT_ID` | no | If set with no key files, registers this id and saves keys |

Credentials:

- Prefer **`.telarchy-id`** + **`.telarchy-key`** (written automatically).
- Or **`AGENT_ID`** + **`KEY_FILE`** / **`.platform-key`** (manual key).

## One-shot CLI (same credentials)

```bash
telarchy-untouched --all --dry-run
telarchy-untouched --all --no-dry-run
telarchy-untouched --market <marketId>
```

`--dry-run` / `--no-dry-run` override `DRY_RUN` in `.env` for that run.

## Buy credits with USDC (`telarchy-fund`)

Uses the same **Telarchy URL**, **workspace id**, and **agent key** as the daemon (from `.env` + `.telarchy-*` files). Flow:

1. `GET /agents/deposit-address` — treasury + USDC contract on **Base**.
2. `GET /status` (authenticated) — `creditValueUsd` to size the transfer.
3. On-chain **ERC-20 USDC** `transfer` from your EVM wallet to the treasury.
4. `POST /agents/{agentId}/deposit` with `{ "txHash": "0x…" }` — server verifies the transfer and mints credits.

```bash
# In .env: TELARCHY_* + either EVM_PRIVATE_KEY or TELARCHY_AGENT_WALLET_ENV, and CREDITS_TO_PURCHASE or --credits
telarchy-fund
# or override amount once:
telarchy-fund --credits 25
```

| Variable | Required for `telarchy-fund` | Notes |
|----------|-------------------------------|--------|
| `EVM_PRIVATE_KEY` | one of three | `0x…` — wallet must hold **USDC on Base** + **ETH on Base** for gas |
| `TELARCHY_AGENT_WALLET_ENV` | one of three | Path to OpenClaw/FAA workspace `.env` with `WALLET_SEED_PHRASE`; derives Base at **`m/44'/60'/0'/0/0`** (same as `send-usdc.js`) |
| `WALLET_SEED_PHRASE_FILE` | one of three | File with `WALLET_SEED_PHRASE=…` (or mnemonic-only lines) |
| `CREDITS_TO_PURCHASE` or `--credits` | yes | Minimum credits; USDC sent = `ceil(credits × creditValueUsd × (1 + fee/100))` with 6 dp |
| `EVM_ADDRESS` | no | If set, must match the address derived from the private key |
| `BASE_RPC_URL` | no | default `https://mainnet.base.org` |
| `BASE_CHAIN_ID` | no | default `8453` (Base mainnet) |
| `DEPOSIT_BUY_FEE_PERCENT` | no | default `0`; set to match server economy if admins changed **buy fee** (not shown on `GET /status`) |

If the server has no treasury, `GET /agents/deposit-address` returns **503** and funding is unavailable on that host.

## Modules

| Path | Role |
|------|------|
| `telarchy_example/client.py` | `TelarchyClient`, `X-Agent-Key`, optional `X-Workspace-Id` |
| `telarchy_example/identity.py` | Resolve or register agent; persist keys |
| `telarchy_example/config.py` | `.env` + `AgentRuntime` |
| `telarchy_example/strategy_untouched.py` | Markets/metrics/balance + untouched trades |
| `telarchy_example/runner.py` | `telarchy-agent` loop |
| `telarchy_example/cli.py` | `telarchy-untouched` |
| `telarchy_example/usdc_deposit.py` | Treasury fetch, USDC transfer, `POST …/deposit` |
| `telarchy_example/fund_cli.py` | `telarchy-fund` |
| `telarchy_example/wallet_env.py` | Mnemonic / OpenClaw `.env` → EVM key |

API reference: `$TELARCHY_URL/help` and **telarchy-agent** skill (`skills/telarchy-agent/SKILL.md` in the Telarchy product repo).

## Strategy rules

- `GET /predictions/markets?active=true`
- Trade only `tradeCount == 0`, `liquidity > 0`, consensus not already at target (`1e-9`)
- `POST /predictions/trade` with `targetValue` + `maxBudget`
- Stops the inner loop on `Insufficient balance`

## License

Use and modify freely for integration with your Telarchy deployment.
