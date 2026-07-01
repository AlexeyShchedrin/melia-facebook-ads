"""`fb leads poll|test` — lead ingestion helpers."""

from __future__ import annotations

import asyncio

import typer

from meta_ads.worker.jobs.lead_poll import run_lead_poll

app = typer.Typer(no_args_is_help=True)


@app.command("poll")
def poll() -> None:
    """Run one reconciliation pass (poll each form for missed leads)."""
    asyncio.run(run_lead_poll())
    typer.echo("lead poll done")


@app.command("test")
def test() -> None:
    """How to generate a free test lead (the engineering gate before go-live)."""
    typer.echo(
        "Use the Lead Ads Testing Tool: https://developers.facebook.com/tools/lead-ads-testing\n"
        "Pick the Page + an active form → Create Lead. It fires a REAL webhook to the CRM relay\n"
        "and creates a resolvable leadgen_id — the whole path (relay → resolve → CRM) runs free."
    )
