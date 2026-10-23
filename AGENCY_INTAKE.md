# Agency Meta intake: compatibility and activation

This change extends the existing resolver and polling journal. It does not start a scheduler, subscribe a Page, change an ad account, issue access grants, send a message, or enable an agency in production.

## Delivery contract

The CRM authenticates the original Meta callback using `X-Hub-Signature-256` and its App Secret. It persists only the signed Page/form/leadgen identifiers in `meta_inbound_leadgen` before replying 200. The existing worker reads `ads_contract.v_meta_inbound`, selects that Page's token and retrieves the lead. Callback and polling both use the same resolver.

The worker signs its resolved JSON with `FB_INGEST_HMAC_SECRET` in `x-fb-signature`. Contract v2 adds `page_id` and `connection_key = meta:<configured App ID>:<verified Page ID>`. The CRM finds the agency using its own registry; a caller-supplied organization cannot select a tenant. The callback signature and the worker signature are separate trust boundaries.

Accepted responses have `ok: true` and one of these shapes:

- Project: `kind: project`, positive integer `leadId`. The old response without `kind` remains readable by the new worker.
- Agency: `kind: agency`, UUID `inquiryId`, UUID or null `leadId`, and `matchStatus: matched | conflict | unresolved`. A conflict with a null client is a successful durable inquiry, not a failed delivery.

The journal stores the first accepted receipt permanently. Both polling and callback retries treat an inquiry UUID as terminal even when its client UUID is null. No agency UUID is cast into `crm_lead_id`. Unknown or contradictory mappings produce a recorded, retryable error and never choose a default tenant.

Explicit old project form/campaign registry rows retain their routing, including historical `project_id = NULL` rows which explicitly mean the legacy default project. An unregistered form/campaign no longer inherits that default. A Page may contain both agency and project forms. Agency forms require v2; an old worker receives `meta_contract_upgrade_required` rather than writing a project client.

## Deployment order and rollback boundary

1. Before deploying the new CRM, compare all active production Meta forms and campaigns with the existing project attribution registry. Resolve unknown or conflicting entries explicitly with the owner. The new CRM rejects unregistered sources immediately on deployment, even while agency sales remain disabled. Do not automatically seed, infer, migrate or reattribute historical leads.
2. Take the normal database backup and verify the exact CRM/worker commits using the shared acceptance profile.
3. Apply worker Alembic `0005_agency_intake_receipts` and CRM `0286_agency_meta_sources` with the existing deployment/migration authorities. Neither migration creates a connection or activates sales.
4. Deploy compatible CRM handlers and the worker together before enabling an agency form. The new worker can read old integer responses; the old worker cannot understand UUID agency receipts.
5. Configure the approved Page/form/optional published property mapping, agency sales latch, integration permissions and worker Page token through the existing authorized operations flow. Tokens stay in the worker, not in the agency UI.

The worker migration preserves old integer-only writers. Its downgrade refuses to remove UUID columns after an agency receipt exists. After activation, rollback must retain a worker/CRM pair that understands agency receipts; do not downgrade the receipt schema or reclassify existing receipts. Disabling a connection stops new agency intake while accepted-event replies remain stable.

## Diagnostics and safe retry

`meta.v_inbound_delivery` exposes only identifiers, receipt kind, attempt counts, timestamps and an allowlisted error category. Raw provider errors, payloads, contacts and tokens are excluded. Migration 0005 grants `USAGE(meta)` and `SELECT` on this view to an existing `melia` role; it does not grant access to worker tables. Verify that the deployed CRM role matches this prerequisite before activation.

CRM services require current agency integration permissions and recheck them in the transaction. They show `not_configured`, `ready_to_test`, `working` or `needs_attention`. A project receipt on a shared Page does not prove agency delivery. `working` requires an actual accepted agency inquiry.

A manual retry references a known failed journal row by connection and leadgen ID plus its exact failure timestamp. The CRM verifies the Page/form mapping, current permissions, enabled source and writable agency. `ads_contract.v_meta_retry_requests` exposes one additional attempt to the existing worker; it is not a payload queue. Once `processed_at` advances, that request is consumed. Accepted inquiries are never retried, including unresolved/conflicting inquiries without a client. Unknown forms must first receive an approved mapping; retry cannot redirect them.

The poller also queries newly active zero-count forms within the normal bounded window. This recovers the first lead even if its callback was lost or the provider's count lagged.

## Synthetic verification

Use a checkout without `.env`, clear provider credentials, set `PYTHONPATH` to this checkout's `src`, and verify `meta_ads.__file__`. No worker daemon or ads CLI is needed.

- Unit contract/polling/answers: `python -m pytest tests/test_ingest_contract.py tests/test_lead_poll.py tests/test_form_answers.py -q`.
- Actual PostgreSQL receipt/migration tests: `python -m pytest tests/test_ingest_receipts_db.py -q`. `AGENCY_META_TEST_DATABASE_URL` must point to a synthetic loopback cluster's `postgres` database. Tests create and remove separate `kvadra_test_meta_*` databases for fresh installation and the actual pre-0005 bigint-only journal, seeded with success and failure. They verify that UUID columns are absent before upgrading the latter. They also test late errors, old integer writers, terminal conflict receipts and one-attempt manual retry.
- CRM owns the HTTP integration suite `tests/db/agency-meta-intake.db.spec.ts`, project `db-agency-meta-isolated`. Set `AGENCY_META_WORKER_ROOT` to this exact checkout and `AGENCY_META_PYTHON` to its compatible interpreter. The suite invokes real Next POST handlers through a local HTTP bridge and runs this Python resolver against the same synthetic PostgreSQL database. Only Graph responses are replaced. It is a cross-service contract test, not a claim that a full Next deployment or real Meta account was tested.
- The helper `tests/fixtures/agency_http_flow.py initialize|run` accepts synthetic JSON on stdin. `run` requires `leadgenId`, `formId`, `pageId`, `fields`; optional `mode` is `callback` or `poll`, and `providerError: true` simulates token expiry. Its JSON stdout contains the persisted receipt; migration logging uses stderr. Both its DB and HTTP URLs must be local and the database must have the `kvadra_test_` prefix.

## Official sources checked on 2026-10-23

The Meta developer pages for [webhook validation](https://developers.facebook.com/docs/graph-api/webhooks/getting-started/), [lead retrieval](https://developers.facebook.com/docs/marketing-api/guides/lead-ads/retrieving/), [test leads](https://developers.facebook.com/docs/marketing-api/guides/lead-ads/testing-troubleshooting/) and [version lifecycle](https://developers.facebook.com/docs/graph-api/changelog/versions) returned HTTP 429 during this review. Their current contents and version sunset dates were not verified.

Accessible primary sources were checked instead:

- Meta's [leads retrieval setup/checker](https://github.com/facebookincubator/catalogue-of-api-solutions/blob/main/solutions/leads/leads-retrieval-set-up-checker.md) describes the Page `leadgen` subscription, lead/form identifiers, single-lead and form-leads retrieval, and one test lead per form with deletion before recreation.
- Meta Business SDK [v25 Lead object](https://github.com/facebook/facebook-python-business-sdk/blob/25.0.0/facebook_business/adobjects/lead.py) and [v25 LeadgenForm object](https://github.com/facebook/facebook-python-business-sdk/blob/25.0.0/facebook_business/adobjects/leadgenform.py) expose the retrieval fields and form/test-lead edges used by this integration.
- Meta's archived WhatsApp SDK [webhook implementation](https://github.com/WhatsApp/WhatsApp-Nodejs-SDK/blob/main/src/api/webhooks.ts) and [signature helper](https://github.com/WhatsApp/WhatsApp-Nodejs-SDK/blob/main/src/utils.ts) demonstrate the shared App-Secret HMAC-SHA256/raw UTF-8 mechanism. This is protocol evidence from an archived SDK, not proof of current Lead Ads permissions or retry policy.
- The current Meta SDK [API configuration](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/apiconfig.py) reports v26.0. This change preserves the repository's existing configurable v25.0 default; it does not upgrade Graph API versions. Recheck the deployed App's version, access grants and v25 availability against Meta's live version documentation before activation.

After authorized real-account connection, create a separate official test lead and verify callback → durable agency inquiry → source status, then repeat polling and confirm no duplicate. No advertising spend is required for that test. The synthetic suite does not replace this final account-specific check.
