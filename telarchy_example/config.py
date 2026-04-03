"""Environment and optional `.env` file loading (stdlib only)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
class Config:
    telarchy_url: str
    agent_id: str
    workspace_id: str | None
    max_budget_per_market: float
    key_file: Path


def read_api_key(key_file: Path) -> str:
    return key_file.read_text(encoding="utf-8").strip()


def load_config(cwd: Path | None = None) -> Config:
    base = cwd or Path.cwd()
    load_env_file(base / ".env")

    agent_id = os.environ.get("AGENT_ID", "").strip()
    if not agent_id:
        raise ValueError("AGENT_ID is required")

    url = os.environ.get("TELARCHY_URL", "https://telarchy.com/api").strip()
    ws = os.environ.get("TELARCHY_WORKSPACE_ID", "").strip() or None
    max_budget = float(os.environ.get("MAX_BUDGET_PER_MARKET", "1"))

    key_path = Path(os.environ.get("KEY_FILE", str(base / ".platform-key"))).expanduser()

    return Config(
        telarchy_url=url,
        agent_id=agent_id,
        workspace_id=ws,
        max_budget_per_market=max_budget,
        key_file=key_path,
    )
