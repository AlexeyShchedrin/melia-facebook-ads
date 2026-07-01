"""Thin async Graph API client + token access.

Tokens live encrypted in `meta.oauth_tokens` (written by `fb auth-bootstrap`);
this module decrypts them on demand. We use raw httpx here rather than the SDK
because the pieces we care about (chunked video upload, leadgen resolve,
Conversions API for CRM) are simpler over HTTP.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import text

from meta_ads.config import get_settings
from meta_ads.security import decrypt_token

logger = logging.getLogger(__name__)

# provider constants (match meta.oauth_tokens.provider)
SYSTEM_USER = "meta_system_user"
PAGE = "meta_page"
DATASET = "meta_dataset"


class GraphError(RuntimeError):
    """A Graph API error response (non-2xx). Carries the parsed error body."""

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self.body = body
        err = body.get("error", {}) if isinstance(body, dict) else {}
        super().__init__(f"Graph {status}: {err.get('message', body)} (code={err.get('code')})")


def default_asset_id(provider: str) -> str:
    """The natural asset a token is scoped to when the caller doesn't specify."""
    s = get_settings()
    if provider == PAGE:
        return s.meta_page_id
    if provider == DATASET:
        return s.meta_dataset_id
    return ""  # System User is account-global here


async def get_token(provider: str, asset_id: str | None = None) -> str:
    """Fetch + decrypt a stored token; fall back to the .env bootstrap value."""
    from meta_ads.db import async_session_maker  # noqa: PLC0415

    if not asset_id:
        asset_id = default_asset_id(provider)

    async with async_session_maker() as session:
        row = (
            await session.execute(
                text(
                    "SELECT encrypted_token FROM meta.oauth_tokens "
                    "WHERE provider = :p AND asset_id = :a"
                ),
                {"p": provider, "a": asset_id},
            )
        ).first()
    if row is not None:
        return decrypt_token(row.encrypted_token)

    s = get_settings()
    if provider == SYSTEM_USER and s.meta_system_user_token.get_secret_value():
        return s.meta_system_user_token.get_secret_value()
    if provider == PAGE and s.meta_page_token.get_secret_value():
        return s.meta_page_token.get_secret_value()
    if provider == DATASET and s.meta_system_user_token.get_secret_value():
        return s.meta_system_user_token.get_secret_value()  # dataset events via System User
    raise RuntimeError(
        f"No token for provider={provider!r} asset_id={asset_id!r} — run `fb auth-bootstrap`."
    )


class GraphClient:
    """One httpx client per provider token. `async with GraphClient(...) as g:`."""

    def __init__(self, token: str) -> None:
        self._token = token
        # base_url MUST end with '/' or httpx's RFC-3986 join drops the version
        # segment ("…/v25.0" + "act_x" → "…/act_x"). Keep the trailing slash.
        self._base = get_settings().graph_base.rstrip("/") + "/"
        self._http = httpx.AsyncClient(base_url=self._base, timeout=120.0)

    @classmethod
    async def for_provider(cls, provider: str, asset_id: str | None = None) -> GraphClient:
        return cls(await get_token(provider, asset_id))

    async def __aenter__(self) -> GraphClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._request("POST", path, data=data, files=files)

    async def delete(self, path: str) -> dict[str, Any]:
        return await self._request("DELETE", path)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        auth = {"access_token": self._token}
        query = {**(params or {}), **auth} if method in ("GET", "DELETE") else params
        form = {**(data or {}), **auth} if method == "POST" else data
        resp = await self._http.request(
            method, path.lstrip("/"), params=query, data=form, files=files
        )
        body: dict[str, Any] = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            raise GraphError(resp.status_code, body)
        return body
