"""Create or load agent id + API key (no manual curl)."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import httpx


def _register_url(base: str) -> str:
    return f"{base.rstrip('/')}/agents/register"


def _try_register(telarchy_url: str, agent_id: str) -> dict | None:
    """POST /agents/register. Returns JSON body, or None if agent id already taken (409)."""
    url = _register_url(telarchy_url)
    resp = httpx.post(url, json={"agentId": agent_id}, timeout=60.0)
    if resp.status_code == 409:
        return None
    if resp.status_code >= 400:
        raise RuntimeError(
            f"POST /agents/register failed -> {resp.status_code}: {resp.text}",
        )
    return resp.json()


def resolve_or_register(base: Path, telarchy_url: str) -> tuple[str, str]:
    """
    Credentials resolution order:
    1. `.telarchy-id` + `.telarchy-key` in `base`
    2. `AGENT_ID` env + key file (`KEY_FILE` or `./.platform-key`)
    3. Auto-register: save `.telarchy-id` + `.telarchy-key` under `base`
    """
    tid = base / ".telarchy-id"
    tkey = base / ".telarchy-key"
    legacy_key = base / ".platform-key"
    key_file = Path(os.environ.get("KEY_FILE", str(legacy_key))).expanduser()
    env_agent = os.environ.get("AGENT_ID", "").strip()

    if tid.is_file() and tkey.is_file():
        return tid.read_text(encoding="utf-8").strip(), tkey.read_text(encoding="utf-8").strip()

    if tid.is_file() and not tkey.is_file():
        raise OSError(
            f"Found {tid} but missing {tkey}. Remove {tid} to re-register, or restore the key file.",
        )
    if tkey.is_file() and not tid.is_file():
        raise OSError(
            f"Found {tkey} but missing {tid}. Remove {tkey} to re-register, or add the agent id file.",
        )

    if env_agent and key_file.is_file():
        return env_agent, key_file.read_text(encoding="utf-8").strip()

    if env_agent and not key_file.is_file():
        body = _try_register(telarchy_url, env_agent)
        if body is None:
            raise RuntimeError(
                f'Agent id "{env_agent}" is already registered but no key file was found at {key_file}. '
                "Use a new AGENT_ID or place the existing API key there.",
            )
        _validate_register_body(body)
        agent_id = str(body["agentId"])
        api_key = str(body["apiKey"])
        base.mkdir(parents=True, exist_ok=True)
        tid.write_text(agent_id + "\n", encoding="utf-8")
        tkey.write_text(api_key + "\n", encoding="utf-8")
        tid.chmod(0o600)
        tkey.chmod(0o600)
        print(f"Registered agent {agent_id}; saved {tid.name} and {tkey.name}.")
        return agent_id, api_key

    for _ in range(12):
        agent_id = f"py-auto-{uuid.uuid4().hex[:14]}"
        body = _try_register(telarchy_url, agent_id)
        if body is None:
            continue
        _validate_register_body(body)
        agent_id = str(body["agentId"])
        api_key = str(body["apiKey"])
        base.mkdir(parents=True, exist_ok=True)
        tid.write_text(agent_id + "\n", encoding="utf-8")
        tkey.write_text(api_key + "\n", encoding="utf-8")
        tid.chmod(0o600)
        tkey.chmod(0o600)
        print(f"Registered agent {agent_id}; saved {tid.name} and {tkey.name}.")
        return agent_id, api_key

    raise RuntimeError("Could not register a new agent id after several attempts.")


def _validate_register_body(body: object) -> None:
    if not isinstance(body, dict):
        raise TypeError(f"unexpected register response: {body!r}")
    if "agentId" not in body or "apiKey" not in body:
        raise ValueError(f"register response missing agentId/apiKey: {json.dumps(body)[:200]}")
