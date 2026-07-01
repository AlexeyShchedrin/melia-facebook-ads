"""`fb sync-now` — one-shot insights sync (smoke test)."""

from __future__ import annotations

import asyncio

import typer

from meta_ads.worker.jobs.perf_pull import run_perf_pull


def sync_now() -> None:
    """Run one insights pull now (smoke test against the ad account)."""
    asyncio.run(run_perf_pull())
    typer.echo("sync done")
