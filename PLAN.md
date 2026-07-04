# facebook-ads (Meta) — план сервиса (v2, риски закрыты by design)

> Составлено: **2026-07-01**. База: [`research/`](research/README.md) (Marketing/Graph API
> v25.0), фактический код `melia-google-ads` (повторяем 1:1) и реальный приём лидов в
> `melia-crm`. v2 переработан после аудита рисков — см. §11 «Что изменилось в v2».

Сервис-спутник по паттерну `google-ads`: заливает **фото/видео креативы** в Meta,
собирает **лиды из лид-форм** в общую CRM и пробрасывает **качество лида обратно** в Meta
(Conversions API for CRM) для оптимизации на качество, а не на объём.

---

## 0. Зафиксированные решения

| # | Развилка | Решение |
|---|---|---|
| 1 | Глубина автоматизации A | **Полная программная сборка**: `adimages`/`advideos` → `AdCreative` → `Campaign→AdSet→Ad`. |
| 1a | Источник креативов | **Локальные папки** (`OneDrive\Desktop\Melia Reels\`, `melia-montage/projects/<slug>/renders/`). Заливка — локальная CLI/MCP-операция. |
| 2 | Приём leadgen-вебхука | **Тонкий relay-route в CRM** (публичная поверхность на `crm.kvadra.me`), но **резолв лида и все Meta-токены — в fb-сервисе**. Мотивация — §4. |
| 3 | MVP | **Реальная лид-форма на живой кампании**. Инженерный гейт до этого — **Lead Ads Testing Tool** (бесплатно, детерминированно). |
| 4 | Ключ CAPI | **Строго по 15–16-значному Meta `lead_id`.** Нет `lead_id` → лид не наш → пропускаем. Хеш PII **никогда** не используется для определения «наш ли лид». Инвариант, не опция (§5). |
| 5 | Деплой серверной части | **Host systemd-сервис** на Hetzner (как реальный `ads-worker`), Postgres по `127.0.0.1:5432`, отдельно от CI/CD CRM. **Публичного HTTP у fb-сервиса нет.** (§8) |
| — | Стек | Python 3.12 / APScheduler / SQLAlchemy async + Alembic / MCP / Typer — зеркало `google-ads`. **FastAPI-`api` таргет не нужен** (нет входящего HTTP). |
| — | Репозиторий / схема | Новый `melia-facebook-ads` (свой git); своя схема **`meta`** в общей БД `melia` (владелец — Alembic fb-сервиса). |
| — | Доступы на старте | Свой Business Manager + System User token → **App Review не нужен**. |

---

## 1. Топология: где что исполняется и где какие токены

```
ЛОКАЛЬНО (Windows, .venv) — CLI `fb` + MCP «kvadra-facebook-ads»
  токен: System User (в локальном .env)              ──▶ Meta Marketing API
  • upload креатива с ДИСКА: advideos(chunked+poll) / adimages           [A]
  • build: Campaign(OUTCOME_LEADS)→AdSet(LEAD_GENERATION)→AdCreative→Ad  [A]
  •        validate_only → PAUSED → (проверка) → ACTIVE
  • create leadgen form (POST /{page_id}/leadgen_forms)                  [A]
  ← сюда «второй агент» берёт готовый рил из melia-montage и грузит в Meta

СЕРВЕР (Hetzner, host systemd — зеркало ads-worker) — fb-worker (APScheduler)
  ВСЕ Meta-токены живут ЗДЕСЬ: System User + Page + dataset (Fernet, meta.oauth_tokens)
  Postgres по 127.0.0.1:5432 ; пишет ТОЛЬКО схему meta ; публичного HTTP нет
  • LISTEN 'meta_leadgen' + poll GET /{form_id}/leads (сверка <90д)       [B]
  •    → resolve GET /{leadgen_id} → POST CRM /api/ads/meta/lead-ingest (HMAC)
  • LISTEN 'ads_outbox' → CAPI for CRM, ключ = Meta lead_id ONLY          [C]
  • perf_pull insights → meta.campaign_metrics ; poll модерации ; budget pacing [A-monitor]

CRM (Next.js, crm.kvadra.me) — ЕДИНСТВЕННЫЙ писатель public.leads
  Meta-токенов для лид-пайплайна ЗДЕСЬ НЕТ — только App Secret + verify_token
  • POST /api/ads/meta/lead-webhook  (тонкий relay)                       [B]
  •    verify X-Hub-Signature-256 (App Secret) → INSERT public.meta_inbound_leadgen
  •    → pg_notify('meta_leadgen', id) → 200 (быстро, асинхронно)
  • POST /api/ads/meta/lead-ingest   (HMAC от fb-worker) → submitCaptureForm()  [B]
  • lifecycle_* → outbox_events (уже пишутся при смене статуса)           [C]
  • contract-view'ы для роли fb_svc: v_meta_inbound, v_leads_meta

          общий Postgres (БД melia): схемы public / meta / ads / ads_contract
```

**Почему так — единый источник Meta-логики.** Meta шлёт в вебхуке **только `leadgen_id`**
(в отличие от Google, который шлёт полные данные), поэтому резолв требует Page-токена и
Graph-вызова + пагинации + учёта 90-дневного окна + rate-limit. Если это положить в CRM
(TypeScript), Meta-логика и токены расползаются по двум языкам и репозиториям, а
токен-lifecycle (инвалидация `458/463/467`) придётся делать дважды. Поэтому CRM держит
**тонкий** relay (только проверка подписи по App Secret + постановка в очередь), а весь
Graph-резолв, polling и токены — в **одном** месте (fb-worker, Python). CRM остаётся
единственным писателем `public.leads`. Публичная поверхность при этом всё равно на CRM —
новый домен/сертификат не нужен.

> Escape hatch: если однажды захочется, чтобы CRM резолвил сам (устранив HTTP-хоп
> fb-worker→CRM) — это возможно, но ценой Page-токена и Graph-логики в CRM. По умолчанию
> не делаем.

**Границы:** CRM пишет только свои `public.*` таблицы (relay пишет `public.meta_inbound_leadgen`,
ингест — через `submitCaptureForm`). fb-сервис читает CRM только через `ads_contract.*`
(роль `fb_svc`, SELECT) и пишет только схему `meta`.

---

## 2. Структура репозитория `melia-facebook-ads`

```
pyproject.toml            # console_scripts: fb = "meta_ads.cli.main:app"
Dockerfile                # targets: worker, mcp  (api НЕ нужен — нет входящего HTTP)
alembic.ini, alembic/     # схема meta
.env                      # абсолютный путь резолвится из корня (как в google-ads)
src/meta_ads/
  config.py               # pydantic-settings, _PROJECT_ROOT/.env (абсолютно)
  security.py             # Fernet; хелпер verify X-Hub-Signature-256; HMAC для ингеста
  channels/
    base.py               # AdChannel ABC (ChannelKind.META уже существует)
    meta/
      client.py           # GraphClient (httpx) + facebook-business SDK, кэш токенов
      creatives.py        # upload_image / upload_video(chunked+poll) / build_creative
      campaigns.py        # create campaign/adset/ad, copy, pause/resume/budget
      leadforms.py        # create/read leadgen_forms
      leads.py            # resolve GET /{leadgen_id}; poll GET /{form_id}/leads
      reporting.py        # insights (async report), moderation state, pacing
      conversions.py      # CAPI for CRM: POST /{dataset_id}/events
  conversions/
    hashing.py            # SHA-256 нормализованных em/ph (как в google-ads)
    taxonomy.py           # CRM-стадия → Meta event_name + value
    capi_drain.py         # v_outbox → CAPI (ключ lead_id), meta.processed_outbox
  ingest/
    resolver.py           # v_meta_inbound → resolve → POST CRM ингест; meta.processed_inbound
  worker/
    main.py               # APScheduler + LISTEN 'meta_leadgen' + LISTEN 'ads_outbox'
    jobs/{lead_resolve,lead_poll,capi_drain,perf_pull,moderation,pacing}.py
  mcp/__main__.py + tools/{read,analytics,planning,mutation}.py
  cli/main.py + commands/{auth,creative,campaign,leads,conversions,sync}.py
  db/{models.py,session.py}
```

**Схема `meta` (Alembic):** `oauth_tokens` (System User + Page + dataset, Fernet),
`campaign_metrics`, `campaign_external_map` (идемпотентность запусков по `spec_hash`),
`conversion_dataset_map` (event_name → dataset_id + default_value), `processed_outbox`
(идемпотентность CAPI по `crm_outbox_id`), `processed_inbound` (идемпотентность лидов по
`leadgen_id`), `pending_mutations` (Telegram-аппрув), `alert`, `creative_upload`
(path+mtime+size → image_hash/video_id, чтобы не грузить дважды), `moderation_state`
(ad_id → review-статус + причины).

---

## 3. Пайплайн A — креативы и кампании (локальный CLI/MCP)

**Заливка с диска** (`channels/meta/creatives.py`) — принимает **локальный путь**:
- Фото: `POST /act_<ID>/adimages` → `images.<name>.hash`.
- Видео: `POST /act_<ID>/advideos` фазами start→transfer→finish → поллинг
  `GET /{video_id}?fields=status` до `ready`. До 4 ГБ / 240 мин.
- Кэш `meta.creative_upload` по (path, mtime, size): один файл не грузим дважды.
- CLI `fb creative upload <path>`; MCP `upload_creative(local_path)` (как `add_image_asset`).

**Сборка кампании** (`channels/meta/campaigns.py`), всё создаём в `PAUSED`:
1. `Campaign`: `objective=OUTCOME_LEADS`, `special_ad_categories=[]`, `status=PAUSED`.
2. `AdSet`: `optimization_goal=LEAD_GENERATION`, `billing_event=IMPRESSIONS`,
   `promoted_object={page_id}`, `destination_type=ON_AD`, `targeting`, `daily_budget`.
   Для IG-плейсментов — `instagram_user_id` (иначе молча не крутится на IG).
3. `AdCreative`: `object_story_spec` с `call_to_action.type=LEAD` +
   `value.lead_gen_form_id=<FORM_ID>`; `video_data.video_id`/`image_hash` из заливки.
4. `Ad`: `creative={creative_id}`, `status=PAUSED` → проверка → `ACTIVE`.

**Money-safety (жёстко):** account-level `spend_cap` = kill-switch; всё в `PAUSED`;
**`execution_options=['validate_only']` на КАЖДОМ create** — ловит серверную валидацию
матрицы `objective↔optimization_goal↔billing_event↔promoted_object` (частый 400) до
реального создания; минимальный дневной бюджет ад-сета; `lifetime_budget`+`end_time` потолок.

**Идемпотентность (у Meta нет idempotency-key):** дедуп по `spec_hash` в
`meta.campaign_external_map` перед create — иначе повтор плодит дубли.

**Мониторинг — на СЕРВЕРЕ, не локально** (fb-worker, §1): поллинг модерации
(`PENDING_REVIEW`/`DISAPPROVED`, `ad_review_feedback`/`issues_info`; правка сбрасывает в
review) в `meta.moderation_state`; budget pacing (алерты дрейфа); insights perf_pull.
Локально — только create/mutate + upload (нужен диск и суждение агента).

---

## 4. Пайплайн B — лиды в CRM (relay в CRM + резолв в fb-worker)

**Изменения в `melia-crm`** (свой репозиторий, ветка `feat/ads-meta-*` по
[integration-workflow](melia-crm/docs/integration-workflow.md)):

*Route 1 — тонкий relay* `app/api/ads/meta/lead-webhook/route.ts`:
- `GET`: handshake — сверить `hub.verify_token`, вернуть сырой `hub.challenge` (200).
- `POST`: проверить **`X-Hub-Signature-256`** (HMAC-SHA256 по сырому телу, App Secret,
  constant-time) → `INSERT public.meta_inbound_leadgen (leadgen_id UNIQUE, form_id, page_id,
  received_at, raw)` (дедуп по `leadgen_id`) → `pg_notify('meta_leadgen', id)` → 200 быстро.
  **Meta-токена здесь нет** — только App Secret + verify_token.

*Route 2 — ингест* `app/api/ads/meta/lead-ingest/route.ts`:
- HMAC-подпись (общий секрет fb↔crm, как у google-ads `X-Ads-Signature`) → маппинг
  Meta-полей → `submitCaptureForm(META_LEAD_SLUG, {...})`. Лид: `source_channel=meta`
  (нормализуется в [`lib/lead-source.ts`](melia-crm/lib/lead-source.ts)),
  `platform=meta_leadgen`, **`fb_lead_id` кладём как ключ дедупа** (`external_row_key` /
  `lead_external_keys`), полный payload в `raw_row`.
- **Атрибуция языка/страны (сделано в CRM, миграция 0147):** payload ОБЯЗАН нести
  `form_id` + `campaign_id` — ингест резолвит их через реестр `campaign_attribution`
  (сигналы `meta_form`/`campaign_registry`; страна — телефон > гео кампании > IP,
  `country_signal`). Живые формы/кампании июля-2026 засижены миграцией; **каждую новую
  форму/кампанию — заводить в реестр ДО запуска** (`/settings/attribution` или
  `POST /api/internal/ads/campaign-attribution`), иначе первый лид даст Telegram-алерт
  «unmapped» и язык определится слабыми сигналами. Свой `locale` fb-worker может слать
  как хинт (`adAttribution.localeHint`) — реестр CRM авторитетнее.

*Миграции CRM* (следующий свободный номер, уточнить на merge — сейчас ~`0141`):
- сид `lead_sources` `kind=meta_lead_form`, метка `"Meta"`;
- таблица `public.meta_inbound_leadgen` + триггер `pg_notify('meta_leadgen')`;
- view `ads_contract.v_meta_inbound` (id, leadgen_id, form_id, page_id) + GRANT `fb_svc`;
- view `ads_contract.v_leads_meta` (см. §5) + GRANT `fb_svc`.

**fb-worker** (`ingest/resolver.py`): LISTEN `meta_leadgen` (+ 30с fallback) → читает
`v_meta_inbound` → `resolve GET /{leadgen_id}?fields=field_data,created_time,ad_id,campaign_id,form_id,platform`
(Page-токен) → маппит `field_data[].{name,values}` → POST в `/api/ads/meta/lead-ingest`
(HMAC) → пишет `meta.processed_inbound` (идемпотентность по `leadgen_id`).

**Polling-сверщик** (`jobs/lead_poll.py`): `GET /{form_id}/leads` с фильтром `created_time`
(окно <90д) → тот же resolve+ингест. Нужен, т.к. доставка вебхука at-least-once, без
гарантии порядка, с дропами. Дедуп на всех путях по `leadgen_id`.

**Качество формы** (меньше мусора): `is_optimized_for_quality`,
`is_phone_sms_verify_enabled` (OTP), кастомные вопросы (↓ prefill-фрод). Обязательный
`privacy_policy` на каждой форме; согласия — `custom_disclaimer.checkboxes`. Перед сбором
Страница принимает **Lead Ads TOS** (в UI).

**Инженерный гейт — Lead Ads Testing Tool:** шлёт настоящий вебхук и создаёт резолвабельный
`leadgen_id` → прогоняем весь путь (подпись → очередь → резолв → ингест → лид в CRM)
детерминированно и бесплатно, до любых трат.

---

## 5. Пайплайн C — качество обратно в Meta (fb-worker)

**🔴 Инвариант анти-контаминации.** Общий `ads_contract.v_outbox` не содержит канала, а
google-воркер грузит конверсию при наличии gclid **или** хеша email/телефона
([outbox_drain.py:170](google-ads/src/ads/conversions/outbox_drain.py)). Если fb-воркер
повторит это, он отправит в Meta CAPI **все** лиды (гугловые, сайтовые); Meta матчит по
хешу PII агрессивно → **ложные Meta-конверсии, порча сигнала качества**. Поэтому:

> fb-worker формирует CAPI-событие **только если у лида есть Meta `lead_id`**. Нет `lead_id`
> → лид не Meta-происхождения → пропускаем (пишем processed-skipped). Хеш PII — лишь
> вторичный сигнал для уже подтверждённых Meta-лидов, **никогда** для определения принадлежности.

Механизм: новый view `ads_contract.v_leads_meta` = `public.leads ⨝ public.lead_external_keys`
(namespace `meta_leadgen_id`), отдаёт `lead_id, meta_lead_id, source_channel, status, email,
phone, name, created_at`. Дрейн джойнит по `lead_id`; `meta_lead_id IS NULL` → skip.

**Дрейн** (`conversions/capi_drain.py`), зеркало `OutboxDrain`:
1. LISTEN `ads_outbox` + поллинг 30с; читаем `v_outbox` LEFT JOIN `meta.processed_outbox`.
2. Джойн `v_leads_meta`; **фильтр `meta_lead_id IS NOT NULL`**.
3. Маппинг (`taxonomy.py`): `lifecycle_qualified→Lead(qualified)`, `deposit→…`,
   `contract→…`, `lifecycle_paid→Purchase/converted` со значениями (стадии →
   `optimization_goal=QUALITY_LEAD`/`CONVERSION_LEADS`). `lead_submitted` **пропускаем** —
   сабмит формы Meta уже знает (событие произошло на её стороне).
4. `POST /{dataset_id}/events`: `event_name`, `event_time`, `action_source="system_generated"`,
   `event_id` (дедуп), `user_data.lead_id` = Meta lead_id (+ опц. хеш `em`/`ph`).
5. Запись в `meta.processed_outbox`.

**Со-улучшение google-ads (опционально):** добавить ему фильтр `source_channel='google'`,
чтобы не грузить Meta/сайтовые лиды в Google вхолостую (не опасно — Google отбрасывает
несовпавшие, — но чище). Это правка **другого** репозитория, вне MVP.

**Нюансы:** ~7 дней сетапа/бэкфила; слать в окне атрибуции; Event Match Quality; отдельный
Offline Conversions API отключён (~2025) — всё через обычный CAPI; setup датасета — `fb setup-datasets`.

---

## 6. Доступы и токены (единый источник)

1. Свой **Business Manager** → app **Business** → продукт **Marketing API** (бесплатно, Dev mode).
2. **System User token** (не истекает) — кампании/креативы/insights. Локальный `.env` + сервер.
3. **Long-lived Page token** (`leads_retrieval`, ADVERTISE на Странице) — резолв лидов. **Только сервер.**
4. **Dataset token** — CAPI. **Только сервер.**
5. Разрешения: `ads_management`, `ads_read`, `business_management`, `leads_retrieval`,
   `pages_show_list`, `pages_read_engagement`, `pages_manage_metadata`. Для **своих**
   ассетов хватает Limited Access — **App Review не нужен**.
6. Принять **Lead Ads TOS**; привязать **funding_source** (иначе `PENDING_BILLING_INFO`);
   выставить account-level `spend_cap`.
7. App Review + Business Verification — только при выходе на клиентские аккаунты.

**Token-lifecycle — один раз, в Python:** `GET /debug_token` для проверки; обработка
инвалидации (`458/463/467` → re-auth); Fernet-хранение (`meta.oauth_tokens`). **CRM
Meta-API-токенов для лид-пайплайна не получает** (только App Secret + verify_token +
HMAC-секрет ингеста). Существующий в CRM `META_ACCESS_TOKEN` используется её собственным
insights-модулем ([lib/meta-api.ts](melia-crm/lib/meta-api.ts)) — оставляем до консолидации
insights (§7, фаза 3).

---

## 7. Дорожная карта

| Фаза | Что | App Review | Гейт проверки |
|---|---|---|---|
| **1 — MVP: живая лид-кампания → лид в CRM** | доступы/токены; локальный upload с диска; билдер `Campaign→AdSet→Ad`+leadgen form; CRM relay+ингест+таблица очереди; fb-worker резолв+polling; funding+spend_cap+TOS | не нужен | **инженерный:** Lead Ads Testing Tool гоняет весь путь; **бизнес:** реальный лид с ACTIVE-кампании падает в CRM как `source_channel=meta` |
| **2 — Качество обратно (C)** | `v_leads_meta`+GRANT `fb_svc`; `conversion_dataset_map`; capi_drain с инвариантом lead_id; taxonomy | не нужен | смена статуса `qualified/paid` → событие видно в Events Manager |
| **3 — Автоматизация и консолидация** | perf_pull в `meta.campaign_metrics`; машина модерации; budget pacing; MCP read/analytics/planning/mutation (dry_run→confirm, `FB_ALLOW_MUTATIONS`); Telegram-аппрувы (long-polling); **консолидация insights** (CRM читает `meta` через view, деприкейт своего meta-pull); больше форматов (`asset_feed_spec` 1:1/4:5/9:16) | не нужен | MCP-«пульт» ведёт кампании; `validate_only` на мутациях |
| **4 — По необходимости** | rate-limit мониторинг (`X-Business-Use-Case-Usage`), таксономия ошибок/бэкофф, **GDPR Data Deletion callback**, мульти-аккаунт | ревью если клиентские | — |

MVP связывает A+B (без кампании и без приёма лида «реальный лид» не показать). Инженерная
готовность доказывается **бесплатно** (testing tool) до трат; «живой лид» зависит от
неинженерных факторов (funding, TOS, модерация ≤24ч, бюджет, живой человек) — закладываем дни.

---

## 8. Деплой серверной части (проверено на боксе 2026-07-01)

Бокс: `root@crm.kvadra.me` (**46.224.41.76**, Hetzner `ubuntu-4gb-fsn1-10`, fsn1). Доступ с
локальной машины по ключу `~/.ssh/id_ed25519`. Проверено прямым SSH (read-only).

**Реальность google-ads (не доки):**
- В проде **только один процесс** — systemd-сервис `ads-worker`. **`ads-api` не существует**
  нигде: в docker только 4 контейнера CRM (`app`, `worker`, `postgres`, `caddy`). Публичного
  `ads.kvadra.me` нет. README/`docker-compose.override.yml` (compose-сервисы + Caddy) —
  **устаревшие, игнорировать** (`override.yml` — это local-dev оверлей).
- Postgres — контейнер CRM, опубликован на `127.0.0.1:5432`; воркер ходит по loopback.
- CI/CD CRM ([ci-cd.yml](melia-crm/.github/workflows/ci-cd.yml)) деплоит только CRM, ads не трогает.

**Фактический `/etc/systemd/system/ads-worker.service`:**
```ini
[Unit]
Description=kvadra google-ads worker (outbox drain + APScheduler)
After=network-online.target docker.service
Wants=network-online.target
[Service]
Type=simple
WorkingDirectory=/opt/google-ads
ExecStart=/opt/google-ads/.venv/bin/python -m ads.worker.main
Restart=always
RestartSec=5
User=root
StandardOutput=journal
StandardError=journal
SyslogIdentifier=ads-worker
[Install]
WantedBy=multi-user.target
```

**Механизм обновления (важно — он ручной и недокументированный):** `/opt/google-ads` — **не
git-репозиторий** (деплой копией/rsync с локальной машины). Пакет `ads 0.1.0` установлен
**editable** (`_editable_impl_ads.pth` → `/opt/google-ads`), поэтому для правок кода хватает
`systemctl restart ads-worker` (без `pip install`). Схема — `.venv/bin/alembic upgrade head`.
`pip install -e .` — только когда меняются зависимости. Деплой-скрипта и CI для воркера нет.
Единственный cron: `0 9 * * * … scripts/token_health.py` (ежедневный токен-health, лог в
`token-health-cron.log`) — **это готовый паттерн токен-мониторинга, зеркалим его для Meta.**

**fb-worker — точное зеркало.** Каталог `/opt/facebook-ads`, свой `.venv`, unit `fb-worker.service`:
```ini
[Unit]
Description=kvadra facebook-ads worker (lead resolve + CAPI drain + APScheduler)
After=network-online.target docker.service
Wants=network-online.target
[Service]
Type=simple
WorkingDirectory=/opt/facebook-ads
ExecStart=/opt/facebook-ads/.venv/bin/python -m meta_ads.worker.main
Restart=always
RestartSec=5
User=root
StandardOutput=journal
StandardError=journal
SyslogIdentifier=fb-worker
[Install]
WantedBy=multi-user.target
```
Деплой: rsync `melia-facebook-ads/` → `/opt/facebook-ads` → (однократно) `python -m venv .venv`
+ `.venv/bin/pip install -e .` → `.venv/bin/alembic upgrade head` → `systemctl enable --now
fb-worker`. Обновление: rsync + `systemctl restart fb-worker`. Meta-токен-health — cron в 09:05.
Без публичного HTTP (вебхук — в CRM). Postgres по `127.0.0.1:5432`.

> Улучшение «в лучшем виде»: оформить эти шаги как `deploy.sh` в репозитории fb-сервиса
> (сейчас у google-ads деплой — «племенное знание»), опционально позже так же завести
> git-checkout+pull на боксе. Не блокер MVP, но убирает ручной rsync.

---

## 9. Управление, GDPR, безопасность

- **GDPR с первого реального лида** (фаза 1 уже собирает реальные PII): правовое основание,
  лимит хранения, зеркалирование 90-дневного окна Meta, путь удаления по запросу. Data
  Deletion **callback** как формальный артефакт — фаза 4 (для App Review), но обрабатывать
  удаление умеем сразу. `privacy_policy` на каждой форме — обязателен.
- **Мутации** гейтятся `dry_run→confirm` + `FB_ALLOW_MUTATIONS` + Telegram-аппрув (как google-ads).
- **Секреты** не в исходниках: Meta-токены — Fernet в `meta.oauth_tokens`; App Secret /
  HMAC-секрет ингеста — в env соответствующих сервисов.

---

## 10. Первые шаги (Фаза 1)

1. Создать `melia-facebook-ads`, `git init`, скаффолд §2, `.env` из `.env.example`.
2. Meta: Business app + Marketing API + System User token; Page token (`leads_retrieval`);
   расшарить `act_<ID>`+Page; Lead Ads TOS; funding_source + `spend_cap`.
3. `fb auth-bootstrap` → Fernet в `meta.oauth_tokens`; `alembic upgrade head`.
4. `fb creative upload <рил из melia-montage>` → `fb campaign create … --validate-only` →
   снять флаг, создать в `PAUSED`.
5. CRM (ветка `feat/ads-meta-*`): миграции (§4), relay-route, ингест-route, view'ы, GRANT
   `fb_svc`. Прогнать весь путь через **Lead Ads Testing Tool**. ← инженерный гейт.
6. Подписать Страницу на `leadgen`, активировать кампанию, поймать реального лида. **MVP.**

---

## 11. Что изменилось в v2 (после аудита рисков)

1. **🔴 CAPI-контаминация закрыта инвариантом** (§5): ключ строго по Meta `lead_id`, иначе
   Meta приписала бы чужие лиды к своей рекламе через хеш PII. Подтверждено по коду google-ads.
2. **Вебхук → тонкий relay в CRM + резолв в fb-worker** (§1, §4): все Meta-токены и
   Graph-логика в одном сервисе/языке; token-lifecycle один раз; CRM без Meta-API-токенов.
3. **Деплой из «открытого вопроса» → подтверждённый факт** (§8): host systemd, без публичного
   HTTP; устаревшие доки помечены.
4. **Мониторинг явно на сервере** (§3): модерация/pacing/insights — fb-worker, не локально.
5. **Дедуп лида по `leadgen_id`** на всех путях (§4); **`spec_hash`** для кампаний (§3).
6. **GDPR с первого лида**, тест-гейт (testing tool) отделён от бизнес-цели (живой лид) (§7, §9).
