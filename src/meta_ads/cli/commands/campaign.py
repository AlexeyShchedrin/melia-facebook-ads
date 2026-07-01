"""`fb campaign create ...` — build a lead campaign (PAUSED, validate_only by default)."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import typer

from meta_ads.channels.meta import campaigns

app = typer.Typer(no_args_is_help=True)


@app.command("create")
def create(
    name: str = typer.Option(..., help="Campaign name"),
    daily_budget_eur: float = typer.Option(5.0, help="Ad set daily budget (EUR)"),
    validate_only: bool = typer.Option(True, help="Server-side dry run (no objects created)"),
) -> None:
    """Create Campaign(OUTCOME_LEADS) -> AdSet(LEAD_GENERATION), PAUSED."""

    async def _run() -> object:
        return await campaigns.create_lead_campaign(
            name=name,
            daily_budget_eur=Decimal(str(daily_budget_eur)),
            targeting={},  # TODO(phase1): pass a real targeting spec
            validate_only=validate_only,
        )

    try:
        typer.echo(asyncio.run(_run()))
    except Exception as exc:  # noqa: BLE001
        typer.secho(f"error: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(1) from exc
