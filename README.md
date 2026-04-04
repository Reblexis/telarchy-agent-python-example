# Telarchy agent (Python example)

Minimal **deterministic** Telarchy participant: HTTP client, **auto-registration** (no manual `curl`), and an optional **long-running loop** that polls active markets and places **untouched-current-value** trades (same rules as FAA `telarchy-untouched-current-value.cjs`).

Not OpenClaw / not an LLM. Credits must exist on the server (operator grant, deposit flow, etc.).

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

## Modules

| Path | Role |
|------|------|
| `telarchy_example/client.py` | `TelarchyClient`, `X-Agent-Key`, optional `X-Workspace-Id` |
| `telarchy_example/identity.py` | Resolve or register agent; persist keys |
| `telarchy_example/config.py` | `.env` + `AgentRuntime` |
| `telarchy_example/strategy_untouched.py` | Markets/metrics/balance + untouched trades |
| `telarchy_example/runner.py` | `telarchy-agent` loop |
| `telarchy_example/cli.py` | `telarchy-untouched` |

API reference: `$TELARCHY_URL/help` and **telarchy-agent** skill (`skills/telarchy-agent/SKILL.md` in the Telarchy product repo).

## Strategy rules

- `GET /predictions/markets?active=true`
- Trade only `tradeCount == 0`, `liquidity > 0`, consensus not already at target (`1e-9`)
- `POST /predictions/trade` with `targetValue` + `maxBudget`
- Stops the inner loop on `Insufficient balance`

## License

Use and modify freely for integration with your Telarchy deployment.
