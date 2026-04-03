"""Thin synchronous HTTP client for the Telarchy agent API."""

from __future__ import annotations

from typing import Any

import httpx


class TelarchyApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        self.method = method
        self.path = path
        self.status = status
        self.body = body
        super().__init__(f"{method} {path} -> {status}: {body}")


class TelarchyClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        workspace_id: str | None = None,
        *,
        timeout_s: float = 60.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._workspace_id = workspace_id
        self._http = httpx.Client(timeout=timeout_s)

    def close(self) -> None:
        self._http.close()

    def request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        if not path.startswith("/"):
            path = "/" + path
        url = f"{self._base}{path}"
        headers: dict[str, str] = {"X-Agent-Key": self._api_key}
        if self._workspace_id:
            headers["X-Workspace-Id"] = self._workspace_id
        if json_body is not None:
            headers["Content-Type"] = "application/json"

        resp = self._http.request(method, url, headers=headers, json=json_body)
        if resp.status_code >= 400:
            raise TelarchyApiError(method, path, resp.status_code, resp.text)

        if not resp.content:
            return None
        return resp.json()
