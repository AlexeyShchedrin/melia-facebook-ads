"""fb-worker entrypoint. APScheduler + two LISTEN/NOTIFY consumers.

Run as: `python -m meta_ads.worker.main` (prod: systemd `fb-worker`, see PLAN.md §8).

Jobs:
- lead_resolve   — LISTEN 'meta_leadgen' + 30 s poll : resolve queued leads → CRM  [B]
- capi_drain     — LISTEN 'ads_outbox'   + 30 s poll : stage events → CAPI          [C]
- lead_poll      — every 15 min : reconcile missed webhooks (<90 d)                  [B]
- perf_pull      — every 15 min : insights → meta.campaign_metrics                   [A]
- moderation     — every 10 min : ad review state                                    [A]
- pacing         — every 30 min : spend vs budget drift                              [A]
"""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from meta_ads import __version__
from meta_ads.config import get_settings
from meta_ads.worker.jobs.capi_drain import listen_for_outbox, run_capi_drain
from meta_ads.worker.jobs.lead_poll import run_lead_poll
from meta_ads.worker.jobs.lead_resolve import listen_for_leadgen, run_lead_resolve
from meta_ads.worker.jobs.moderation import run_moderation_poll
from meta_ads.worker.jobs.pacing import run_budget_pacing
from meta_ads.worker.jobs.perf_pull import run_perf_pull


def _configure_logging() -> None:
    logging.basicConfig(
        level=get_settings().fb_log_level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    # httpx logs full request URLs at INFO — Graph URLs carry access_token as a
    # query param, so that would leak tokens into the journal. Quiet it down.
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def _run() -> None:
    _configure_logging()
    settings = get_settings()
    log = logging.getLogger("meta_ads.worker")
    log.info("fb-worker starting (version=%s, tz=%s)", __version__, settings.fb_timezone)

    scheduler = AsyncIOScheduler(timezone=settings.fb_timezone)

    def _job(coro_fn, name):  # type: ignore[no-untyped-def]
        async def _wrapped() -> None:
            try:
                await coro_fn()
            except Exception:
                log.exception("%s job failed", name)
        return _wrapped

    scheduler.add_job(_job(run_lead_resolve, "lead_resolve"), IntervalTrigger(seconds=30), id="lead_resolve", replace_existing=True)
    scheduler.add_job(_job(run_capi_drain, "capi_drain"), IntervalTrigger(seconds=30), id="capi_drain", replace_existing=True)
    scheduler.add_job(_job(run_lead_poll, "lead_poll"), IntervalTrigger(minutes=15), id="lead_poll", replace_existing=True)
    scheduler.add_job(_job(run_perf_pull, "perf_pull"), IntervalTrigger(minutes=15), id="perf_pull", replace_existing=True)
    scheduler.add_job(_job(run_moderation_poll, "moderation"), IntervalTrigger(minutes=10), id="moderation", replace_existing=True)
    scheduler.add_job(_job(run_budget_pacing, "pacing"), IntervalTrigger(minutes=30), id="pacing", replace_existing=True)

    scheduler.start()
    log.info("scheduler started (jobs=%d)", len(scheduler.get_jobs()))

    stop_event = asyncio.Event()

    def _request_stop(*_: object) -> None:
        log.info("shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_stop)

    # Live NOTIFY consumers alongside the scheduler.
    tasks = [
        asyncio.create_task(listen_for_leadgen(stop_event)),
        asyncio.create_task(listen_for_outbox(stop_event)),
    ]

    try:
        await stop_event.wait()
    finally:
        scheduler.shutdown(wait=False)
        for t in tasks:
            t.cancel()
        for t in tasks:
            with suppress(asyncio.CancelledError):
                await t
        log.info("fb-worker stopped")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
