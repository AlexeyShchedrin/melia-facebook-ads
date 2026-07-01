"""`fb auth-bootstrap` — encrypt the .env Meta tokens into meta.oauth_tokens.

System User + Page tokens are long-lived / non-expiring, so bootstrapping from
.env once is enough; re-run to rotate. (No OAuth callback dance like Google —
System User tokens are minted in Business Manager.)
"""

from __future__ import annotations

import asyncio

import typer
from sqlalchemy import text

from meta_ads.channels.meta.client import DATASET, PAGE, SYSTEM_USER
from meta_ads.config import get_settings
from meta_ads.security import encrypt_token


async def _store(provider: str, asset_id: str, token: str) -> None:
    from meta_ads.db import async_session_maker  # noqa: PLC0415

    async with async_session_maker() as session:
        await session.execute(
            text(
                "INSERT INTO meta.oauth_tokens (provider, asset_id, encrypted_token, scopes) "
                "VALUES (:p, :a, :t, '[]'::jsonb) "
                "ON CONFLICT (provider, asset_id) DO UPDATE SET "
                "encrypted_token = EXCLUDED.encrypted_token, updated_at = now()"
            ),
            {"p": provider, "a": asset_id, "t": encrypt_token(token)},
        )
        await session.commit()


def bootstrap() -> None:
    """Read tokens from .env, encrypt, and upsert into meta.oauth_tokens."""
    s = get_settings()
    stored = []

    async def _run() -> None:
        su = s.meta_system_user_token.get_secret_value()
        if su:
            await _store(SYSTEM_USER, "", su)  # System User is account-global here
            stored.append("system_user")
        pg = s.meta_page_token.get_secret_value()
        if pg:
            await _store(PAGE, s.meta_page_id, pg)
            stored.append("page")
        # Dataset uses the System User token unless a separate one is provided.
        if su and s.meta_dataset_id:
            await _store(DATASET, s.meta_dataset_id, su)
            stored.append("dataset")

    asyncio.run(_run())
    if stored:
        typer.echo(f"stored/updated tokens: {', '.join(stored)}")
    else:
        typer.echo("no tokens found in .env — set META_SYSTEM_USER_TOKEN / META_PAGE_TOKEN")
