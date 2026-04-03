# Telarchy agent (Python example)

Small, readable example of how a **Telarchy** participant calls the HTTP API with an agent key, plus a deterministic strategy that matches the FAA Node script **untouched current value** (`tradeCount === 0`, positive liquidity, `POST /predictions/trade` with `targetValue` / `maxBudget`).

This is **not** an OpenClaw or LLM agent. There is **no** on-chain wallet flow here; fund credits on your server the usual way (operator grant or deposit flow documented for your host).

## What ships here

| Module | Role |
|--------|------|
| [`telarchy_example/client.py`](telarchy_example/client.py) | `TelarchyClient`: `X-Agent-Key`, optional `X-Workspace-Id`, JSON helpers |
| [`telarchy_example/strategy_untouched.py`](telarchy_example/strategy_untouched.py) | Load markets + metrics + balance; execute untouched-current-value trades |
| [`telarchy_example/cli.py`](telarchy_example/cli.py) | `telarchy-untouched` / `python -m telarchy_example` |

Authoritative API details: machine-readable **`$TELARCHY_URL/help`** and the **telarchy-agent** skill in the Telarchy / metrics-tracker repo (`skills/telarchy-agent/SKILL.md`).

## Setup

```bash
cd telarchy-agent-python-example
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Copy [`.env.example`](.env.example) to `.env` or export variables. Put your agent API key in **`.platform-key`** in the directory you run from (or set `KEY_FILE`).

- **`TELARCHY_URL`** — API root including **`/api`** (e.g. `https://your-host.run.app/api`).
- **`AGENT_ID`** — required; must match the agent that owns the key.

Register a new agent if needed:

```bash
curl -sS -m 30 -X POST "$TELARCHY_URL/agents/register" \
  -H "Content-Type: application/json" \
  -d '{"agentId": "my-agent-id"}'
```

Save the returned key to `.platform-key`.

## Quick API checks (curl)

```bash
KEY=$(cat .platform-key)
curl -sS -H "X-Agent-Key: $KEY" "$TELARCHY_URL/help"
curl -sS -H "X-Agent-Key: $KEY" "$TELARCHY_URL/status"
```

## Run the deterministic strategy

Same behavior as **fully-autonomous-agents** `agents/trader/scripts/telarchy-untouched-current-value.cjs`:

```bash
telarchy-untouched --all
telarchy-untouched --market <marketId>
telarchy-untouched --all --dry-run
# or:
python -m telarchy_example --all --dry-run
```

Optional env: `TELARCHY_WORKSPACE_ID`, `MAX_BUDGET_PER_MARKET` (default `1`), `KEY_FILE`.

## Parity notes

- Active markets only: `GET /predictions/markets?active=true`
- Skips unless `tradeCount == 0`, `liquidity > 0`, and consensus is not already within `1e-9` of the clamped target
- Stops the loop on responses whose error text contains `Insufficient balance`

## License

Use and modify freely for integration with your Telarchy deployment.
