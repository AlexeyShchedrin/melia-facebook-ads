# 01 — MCP-серверы для Meta Ads

> Все перечисленные серверы **проверены на реальность** (не галлюцинации): каждый GitHub-репозиторий / PyPI-пакет / hosted-продукт резолвится и соответствует описанию. Но многие capability-claims взяты из README и не проверялись по коду — там, где так, помечено.

## Сводная таблица

| Сервер | Инструменты / возможности | Креативы | Lead-формы / лиды | Auth | Зрелость |
|---|---|---|---|---|---|
| **Meta «Ads AI Connectors»** (ОФИЦИАЛЬНЫЙ) | ~29 инстр.: кампании (создание+правка), каталог, инсайты, диагностика датасетов/аккаунта | Да (создание/правка объявлений) | ❌ **Нет** | Meta Business OAuth, без dev-app и App Review | 🟢 Официальный, open beta с 2026-04-29 |
| **pipeboard-co/meta-ads-mcp** | 42+ инстр.: полный CRUD кампаний/ад-сетов/объявлений, таргетинг-поиск, инсайты, dynamic creative | 🖼 Только фото; **видео нет** | ❌ Нет | через облако Pipeboard (OAuth/token) | 🟢 ~1000★, самый живой community |
| **byadsco/meta-ads-mcp** | ~97 инстр.: кампании, аудитории, отчёты, биллинг, модерация комментов, агентские мульти-аккаунты | Фото+видео (заявлено) | ✅ Заявлено | Sign-in with Meta / System User / API-key | 🟡 8★, активный, непроверенный |
| **mikusnuz/meta-ads-mcp** | 135 инстр. (TS), таргет v25.0 | Фото+видео (заявлено) | ✅ Заявлено | env-токен Meta напрямую | 🟡 54★, README-claims |
| **gomarble-ai/facebook-ads-mcp-server** | ~20 инстр., **только чтение** + аналитика | ❌ | ❌ | User token с `ads_read` | 🟢 333★, MIT, надёжный read-only |
| **hashcott/meta-ads-mcp-server** | 54 инстр. (35 read + 19 write, write выключены по умолчанию) | 🖼 Фото да; видео не подтв. | ❌ | User token, env/CLI | 🟡 9★, безопасный дизайн (write-гейт) |
| **Mike25app/scaleforge-mcp-meta-ads** | 32 инстр., прод-хардненинг (rate-limit, батчинг, pre-flight) | Фото+видео ✅ подтв. | ❌ | env `META_ACCESS_TOKEN` / System User | 🟡 ~0★, но purpose-built |
| **brijr/meta-mcp** | 39 инстр., self-hosted на Cloudflare Workers, multi-tenant JWT | частично (не подтв.) | ❌ | свой OAuth + JWT, свой Meta app | 🟢 188★ — хорошая **референс-база** |
| **Zapier Facebook Lead Ads MCP** (hosted) | Только триггер «New Lead» | ❌ | ✅ Только лиды | Zapier-managed OAuth | 🟢 Коммерческий, узкий |
| **Coupler.io Facebook Ads MCP** (hosted) | Разговорная аналитика по данным | ❌ | ❌ | Coupler-managed | 🟢 Коммерческий, read-only |

## Детали по ключевым серверам

### 🟢 Официальный Meta «Ads AI Connectors»
- **Эндпоинт:** `https://mcp.facebook.com/ads` (remote MCP). **CLI:** npm `@meta/ads-cli`.
- Запущен **2026-04-29**, бесплатная open beta.
- ~29 инструментов: reporting/insights, campaign management (создание И редактирование кампаний/ад-сетов/объявлений на естественном языке), product catalog, диагностика датасетов/сигналов, диагностика аккаунта.
- **Auth:** Meta Business OAuth прямо (read / read-write / read-write-financial per ad account) — **без создания dev-app, без App Review, без ручных токенов**. Клиент показывает «Authenticate with Meta».
- Работает с Claude, ChatGPT, Cursor, Claude Code (CLI).
- ⚠️ **НЕ делает Lead-формы и не выгружает лидов** (подтверждено: после сабмита лида у MCP нет инструментов). Для лидов — отдельный пайплайн (см. [03](03-lead-ads-crm.md)).
- Вердикт: лучший вариант для **интерактивного** управления кампаниями голосом/чатом. Для продакшн-пайплайна с лидами — недостаточно.

### 🟢 pipeboard-co/meta-ads-mcp (самый популярный community)
- GitHub `pipeboard-co/meta-ads-mcp`, PyPI `meta-ads-mcp`. Python. ~1000★, v1.0.117 (2026-06-08), лицензия **BUSL-1.1** (source-available, станет Apache-2.0 в 2029).
- Инструменты: `create_campaign`, `create_adset`, `update_adset`, `create_ad`, `update_ad`, `create_ad_creative` (из `image hash`), `upload_ad_image`, `get_insights` (разбивки + окна атрибуции), поиск таргетинга (`search_interests`, `search_behaviors`, `search_demographics`, `search_geo_locations`), bid-стратегии.
- 🖼 **Только загрузка картинок** (`upload_ad_image`). **Видео нет.** Lead-форм нет.
- ⚠️ Auth по умолчанию идёт **через облако Pipeboard**, не прямой Meta OAuth. Есть режим локального streamable-HTTP.

### 🟢 gomarble-ai/facebook-ads-mcp-server (лучший read-only)
- Python, ~333★, MIT. **Только чтение**: списки кампаний/ад-сетов/объявлений, инсайты (account/campaign/adset/ad), история изменений. Нет create/update, нет загрузки, нет лидов. Отлично для анализа.

### 🟡 Серверы, заявляющие видео + Lead-формы (непроверенные)
- **byadsco/meta-ads-mcp** — ~97 инстр., включая Creatives (image+video) и Leads (формы + retrieval), биллинг, модерацию, агентские мульти-аккаунты. 8★, активный (v3.3.0, 2026-06-09).
- **mikusnuz/meta-ads-mcp** — 135 инстр., TS, таргет v25.0, заявлены `upload_image`+`upload_video` и Leads (5 инстр.). 54★.
- ⚠️ Оба заявляют «всё» в README, но незрелые и не верифицированы по коду. Использовать с осторожностью, проверять на своём аккаунте.

## ⚠️ Не то, что ищешь (часто всплывают в поиске)

- **RamsesAguirre777/facebook-ads-library-mcp** (89★) — это **публичная Ad Library** (разведка по ЧУЖОЙ рекламе), НЕ управление своей. `trypeggy/facebook-ads-library-mcp` — то же самое.
- **serkanhaslak/meta-mcp** (4★) — дефолт `META_API_VERSION=v28.0`, **такой версии не существует** (актуальная v25.0) → сломан из коробки.
- **codprocess/facebook-ads-mcp** (6★) — это Node/Express REST-приложение («Management Control Panel»), **«MCP» ≠ Model Context Protocol**. Не MCP-сервер.
- **oliverames/meta-mcp-server** (17★) — **ЗААРХИВИРОВАН 2026-05-15**, не для прода. Полезен только как «карьер» реализаций инструментов (200+ tools across 7 платформ, включая lead retrieval).
- **mikdeangelis/mcp-meta-ads** — Glama помечает «cannot be installed / quality not tested», API v21.0 (старый).

## Кросс-факт (важно для ВСЕХ write-серверов)

С **v25.0** кампании **Advantage+ Shopping (ASC)** и **Advantage+ App (AAC)** больше **нельзя создавать/редактировать** через Marketing API (распространяется на все версии к ~2026-05-19). Это касается любого write-сервера, не только официального.

## Вывод

| Задача | Рекомендация |
|---|---|
| Интерактивно управлять кампаниями через ассистента | **Официальный Meta MCP** |
| Только аналитика/отчёты голосом | gomarble (self-host) или Coupler.io (hosted) |
| Продакшн-пайплайн (креативы + кампании + Lead-формы + лиды в CRM) | **Строить на Marketing API / SDK самому**; MCP держать как «пульт» сверху |
| Референс-код для своего self-hosted MCP | `brijr/meta-mcp` (188★, multi-tenant, Cloudflare Workers) |
