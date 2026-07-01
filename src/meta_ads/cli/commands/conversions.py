"""`fb setup-datasets` / `fb drain-outbox` — Conversions API for CRM helpers."""

from __future__ import annotations

import asyncio

import typer
from sqlalchemy import text

from meta_ads.config import get_settings
from meta_ads.conversions.capi_drain import CapiDrain
from meta_ads.conversions.taxonomy import OUTBOX_KIND_TO_EVENT


def setup_datasets() -> None:
    """Seed meta.conversion_dataset_map from the taxonomy → META_DATASET_ID.

    CAPI needs no event pre-registration on Meta's side — events appear in
    Events Manager as they arrive. This just tells the drain which dataset each
    funnel event goes to (and its default EUR value). Upsert, safe to re-run.
    """
    s = get_settings()
    if not s.meta_dataset_id:
        typer.secho("META_DATASET_ID is not set", err=True, fg=typer.colors.RED)
        raise typer.Exit(1)

    async def _run() -> list[str]:
        from meta_ads.db import async_session_maker  # noqa: PLC0415

        seeded: list[str] = []
        async with async_session_maker() as session:
            for event_name, default_value in OUTBOX_KIND_TO_EVENT.values():
                await session.execute(
                    text(
                        "INSERT INTO meta.conversion_dataset_map "
                        "(event_name, dataset_id, default_value_eur, is_active) "
                        "VALUES (:e, :d, :v, true) "
                        "ON CONFLICT (event_name, dataset_id) DO UPDATE SET "
                        "default_value_eur = EXCLUDED.default_value_eur, is_active = true"
                    ),
                    {"e": event_name, "d": s.meta_dataset_id, "v": default_value},
                )
                seeded.append(event_name)
            await session.commit()
        return seeded

    seeded = asyncio.run(_run())
    typer.echo(f"dataset {s.meta_dataset_id}: seeded {len(seeded)} events: {', '.join(seeded)}")


def drain_outbox(
    limit: int = typer.Option(100, help="Max events per pass"),
    dry_run: bool = typer.Option(True, help="Don't actually upload to Meta"),
) -> None:
    """Force one CAPI outbox-drain pass (keyed strictly on Meta lead_id)."""
    outcome = asyncio.run(CapiDrain().drain(limit=limit, dry_run=dry_run))
    typer.echo(
        f"fetched={outcome.fetched} uploaded={outcome.uploaded} "
        f"skipped={outcome.skipped} deferred={outcome.deferred} failed={outcome.failed}"
    )
