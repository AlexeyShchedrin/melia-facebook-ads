"""Shared helpers for ops batch scripts against the Meta Marketing API.

- .env loading (facebook-ads repo root), token masking for all logs
- graph() call wrapper with exponential backoff on rate-limit codes 17/613/80004
  (+ neighbours 4/80005) and transient HTTP 429/5xx
- paged GET helper

Never print the raw token: use mask() for anything log-bound.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"

GRAPH = "https://graph.facebook.com"

# Rate-limit / throttling error codes worth a backoff-retry.
BACKOFF_CODES = {4, 17, 613, 80004, 80005}
# seconds: 30, 60, 120, 240, 480, 600
BACKOFF_STEPS = [30, 60, 120, 240, 480, 600]


def load_env(path: Path = ENV_PATH) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def mask(secret: str) -> str:
    if not secret:
        return "<empty>"
    return f"{secret[:8]}…({len(secret)} chars)"


class Api:
    def __init__(self, env: dict[str, str] | None = None):
        env = env or load_env()
        self.token = env["META_SYSTEM_USER_TOKEN"]
        self.version = env.get("META_API_VERSION", "v25.0")
        self.account = env["META_AD_ACCOUNT_ID"]  # act_...
        self.page_id = env.get("META_PAGE_ID", "")
        self.session = requests.Session()

    # ------------------------------------------------------------------
    def graph(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
        timeout: int = 300,
        max_attempts: int = len(BACKOFF_STEPS) + 1,
    ) -> dict:
        """One Graph API call with backoff on throttling codes.

        Raises RuntimeError with the (token-free) error payload on hard failure.
        """
        url = f"{GRAPH}/{self.version}/{path.lstrip('/')}"
        params = dict(params or {})
        params["access_token"] = self.token

        last_err: dict | str = ""
        for attempt in range(max_attempts):
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params if method.upper() == "GET" else {"access_token": self.token},
                    data=data if method.upper() != "GET" else None,
                    files=files,
                    timeout=timeout,
                )
            except requests.RequestException as exc:  # network blip
                last_err = f"network: {type(exc).__name__}: {exc}"
                self._sleep(attempt, last_err)
                continue

            if resp.status_code == 200:
                return resp.json()

            try:
                err = resp.json().get("error", {})
            except Exception:
                err = {"message": resp.text[:500]}
            last_err = {k: err.get(k) for k in ("message", "type", "code", "error_subcode", "error_user_msg")}

            code = err.get("code")
            if code in BACKOFF_CODES or resp.status_code in (429, 500, 502, 503, 504):
                self._sleep(attempt, last_err)
                continue
            raise RuntimeError(f"graph {method} {path} failed hard: {json.dumps(last_err, ensure_ascii=False)}")

        raise RuntimeError(f"graph {method} {path} exhausted retries: {json.dumps(last_err, ensure_ascii=False)}")

    def _sleep(self, attempt: int, why) -> None:
        delay = BACKOFF_STEPS[min(attempt, len(BACKOFF_STEPS) - 1)]
        print(f"    [backoff] attempt {attempt + 1} -> sleep {delay}s ({json.dumps(why, ensure_ascii=False)[:200]})", flush=True)
        time.sleep(delay)

    # ------------------------------------------------------------------
    def get_all(self, path: str, params: dict | None = None, limit: int = 200) -> list[dict]:
        """GET with cursor paging, returns concatenated data[]."""
        params = dict(params or {})
        params["limit"] = limit
        out: list[dict] = []
        after = None
        while True:
            p = dict(params)
            if after:
                p["after"] = after
            chunk = self.graph("GET", path, params=p)
            out.extend(chunk.get("data", []))
            after = chunk.get("paging", {}).get("cursors", {}).get("after")
            if not after or not chunk.get("paging", {}).get("next"):
                break
        return out
