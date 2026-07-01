# melia-facebook-ads

Meta (Facebook/Instagram) ads + lead-gen service for Melia Budva Hotel & Residences.

Sibling of `melia-google-ads`. Same Hetzner host, shared Postgres cluster
(own schema `meta`). **Read [`PLAN.md`](PLAN.md) first** — it holds the full
architecture, the risk decisions (v2), and the deployment facts.

## What it does

- **Creatives + campaigns (A)** — uploads photo/video **from local disk** and builds
  `Campaign→AdSet→Ad` with a lead form. Runs **locally** (CLI/MCP) — needs disk access.
- **Leads (B)** — Meta leadgen webhook is a *thin relay in melia-crm*; this worker
  resolves the lead via Graph and POSTs it to the CRM ingest route + polls for reconciliation.
- **Quality feedback (C)** — drains the CRM outbox and sends stage events to
  **Conversions API for CRM**, keyed **strictly on the Meta `lead_id`** (see PLAN.md §5).

## Stack

Python 3.11+ · `facebook_business` (Marketing/Graph API v25.0) + httpx ·
SQLAlchemy 2.x async + Alembic on schema `meta` · APScheduler · MCP · Typer CLI (`fb …`).

There is **no inbound HTTP** — the public webhook lives in melia-crm. In prod only
the `fb-worker` systemd service runs (outbound + LISTEN/NOTIFY).

## Layout

```
src/meta_ads/
    channels/     AdChannel ABC + Meta impl (client, creatives, campaigns, leadforms, leads, reporting, conversions)
    conversions/  hashing + CRM-stage→Meta-event taxonomy + CAPI outbox drain
    ingest/       leadgen resolve → CRM ingest (idempotent by leadgen_id)
    worker/       APScheduler jobs (lead_resolve, capi_drain, lead_poll, perf_pull, moderation, pacing)
    mcp/          MCP server (read/analytics/planning/mutation, dry_run+confirm gated)
    cli/          Typer entrypoint (`fb`)
    db/           SQLAlchemy models (schema `meta`), session
```

## Local dev

```bash
python -m venv .venv
.venv\Scripts\activate         # Windows
pip install -e ".[dev]"
cp .env.example .env            # fill in Meta app + tokens + FB_* secrets
alembic upgrade head
fb auth-bootstrap               # encrypt System User + Page + dataset tokens into meta.oauth_tokens
fb creative upload "C:\Users\avshc\OneDrive\Desktop\Melia Reels\<file>.mp4"
```

## MCP registration (Claude Code, from the workspace)

Add to `kvadra-workspace/.mcp.json` (after the venv exists):

```json
"kvadra-facebook-ads": {
  "command": "C:\\Users\\avshc\\facebook-ads\\.venv\\Scripts\\python.exe",
  "args": ["-m", "meta_ads.mcp"]
}
```

## Deployment

Host systemd service `fb-worker` on the Hetzner box — see [`PLAN.md`](PLAN.md) §8.
`./deploy.sh` rsyncs, installs, migrates, and restarts. `.env` is created once on the box.
