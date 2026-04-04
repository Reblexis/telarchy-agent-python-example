"""Environment, optional `.env` file, and resolved agent runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from telarchy_example.identity import resolve_or_register


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        if "=" not in trimmed:
            continue
        key, raw_value = trimmed.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key or key in os.environ:
            continue
        value = raw_value.strip().strip("'\"")
        os.environ[key] = value


@dataclass(frozen=True)
class AgentRuntime:
    telarchy_url: str
    agent_id: str
    api_key: str
    workspace_id: str | None
    max_budget_per_market: float
    poll_interval_seconds: float
    dry_run: bool
    trade_post_delay_seconds: float
    trade_rate_limit_backoff_seconds: float


def load_agent_runtime(cwd: Path | None = None) -> AgentRuntime:
    base = cwd or Path.cwd()
    load_env_file(base / ".env")

    url = os.environ.get("TELARCHY_URL", "").strip()
    if not url:
        raise ValueError(
            "TELARCHY_URL is required (must include /api, e.g. http://127.0.0.1:8080/api)",
        )

    ws = os.environ.get("TELARCHY_WORKSPACE_ID", "").strip() or None
    max_budget = float(os.environ.get("MAX_BUDGET_PER_MARKET", "1"))
    poll_interval = float(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
    dry_run = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
    backoff = float(os.environ.get("TRADE_RATE_LIMIT_BACKOFF_SECONDS", "65"))

    delay_raw = os.environ.get("TRADE_POST_DELAY_SECONDS")
    if delay_raw is not None and delay_raw.strip() != "":
        trade_post_delay = float(delay_raw)
    else:
        trade_post_delay = 0.0 if dry_run else 1.0

    agent_id, api_key = resolve_or_register(base, url)

    return AgentRuntime(
        telarchy_url=url,
        agent_id=agent_id,
        api_key=api_key,
        workspace_id=ws,
        max_budget_per_market=max_budget,
        poll_interval_seconds=poll_interval,
        dry_run=dry_run,
        trade_post_delay_seconds=trade_post_delay,
        trade_rate_limit_backoff_seconds=backoff,
    )
