"""`fb` — Typer CLI for the Meta ads service."""

from __future__ import annotations

import contextlib
import sys

import typer

from meta_ads import __version__
from meta_ads.cli.commands import auth, campaign, conversions, creative, leads, sync

# Windows consoles default to cp1252 and raise UnicodeEncodeError on non-ASCII
# in help/output. Force UTF-8 on the streams so `fb --help` etc. never crash.
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

app = typer.Typer(no_args_is_help=True, help="Meta (Facebook/Instagram) ads CLI - Melia Budva")

# grouped
app.add_typer(creative.app, name="creative", help="Upload creatives from local disk")
app.add_typer(campaign.app, name="campaign", help="Build / manage campaigns")
app.add_typer(leads.app, name="leads", help="Lead ingestion helpers")

# top-level
app.command("auth-bootstrap")(auth.bootstrap)
app.command("setup-datasets")(conversions.setup_datasets)
app.command("drain-outbox")(conversions.drain_outbox)
app.command("sync-now")(sync.sync_now)


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
