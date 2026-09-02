"""`fb leads poll|test|form-questions` — lead ingestion helpers."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

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
        "Pick the Page + an active form -> Create Lead. It fires a REAL webhook to the CRM relay\n"
        "and creates a resolvable leadgen_id - the whole path (relay -> resolve -> CRM) runs free."
    )


@app.command("form-questions")
def form_questions(
    form_ids: Annotated[
        list[str] | None,
        typer.Argument(help="Form ids to fetch (default: every form of every configured Page)."),
    ] = None,
    page_id: Annotated[
        str | None,
        typer.Option("--page-id", help="Page owning the given forms (default: the primary Page)."),
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print {form_id: form} JSON - the CRM backfill's input.")
    ] = False,
) -> None:
    """Fetch + cache instant-form question definitions (the labels behind lead answers)."""
    asyncio.run(_form_questions(form_ids or [], page_id, as_json))


async def _form_questions(form_ids: list[str], page_id: str | None, as_json: bool) -> None:
    from meta_ads.channels.meta.leadforms import list_forms  # noqa: PLC0415
    from meta_ads.config import get_settings  # noqa: PLC0415
    from meta_ads.db import async_session_maker  # noqa: PLC0415
    from meta_ads.ingest.form_answers import FormQuestionsCache  # noqa: PLC0415

    targets: list[tuple[str, str | None]] = [(f, page_id) for f in form_ids]
    if not targets:
        for pid in get_settings().page_ids:
            targets.extend((str(f["id"]), pid) for f in await list_forms(pid) if f.get("id"))

    cache = FormQuestionsCache()
    out: dict[str, Any] = {}
    async with async_session_maker() as session:
        for fid, pid in targets:
            form = await cache.fetch(session, fid, pid)
            if form is None:
                typer.echo(f"{fid}: fetch failed (see log)", err=True)
                continue
            out[fid] = form
            if as_json:
                continue
            qs = form.get("questions") or []
            typer.echo(f"{fid} {form.get('name')} locale={form.get('locale')} questions={len(qs)}")
            for q in qs:
                opts = [(o.get("key"), o.get("value")) for o in q.get("options") or []]
                typer.echo(f"    {q.get('type')} {q.get('key')} | {q.get('label')} | {opts}")
        try:
            await session.commit()
        except Exception as exc:  # noqa: BLE001 - no DB locally: the labels still print
            typer.echo(f"cache not persisted: {exc}", err=True)
    if as_json:
        typer.echo(json.dumps(out, ensure_ascii=False, indent=1))
