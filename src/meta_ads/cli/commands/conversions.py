"""`fb setup-datasets` / `fb drain-outbox` — Conversions API for CRM helpers."""

from __future__ import annotations

import asyncio

import typer

from meta_ads.conversions.capi_drain import CapiDrain


def setup_datasets() -> None:
    """Register the funnel-stage events in the Conversions API dataset and seed
    meta.conversion_dataset_map. TODO(phase2)."""
    typer.echo("[skeleton] TODO(phase2): create dataset events + seed conversion_dataset_map")


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
