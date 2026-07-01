# 04 — Доступы, аутентификация, рейт-лимиты (production access)

## Что нужно для прода (чек-лист)

1. **Meta app типа «Business»** + продукт **Marketing API** (создание бесплатно, без ревью; app стартует в Development mode).
2. **Разрешения** на нужном уровне доступа (см. ниже).
3. **System User token** (не истекает по времени) — для сервер-к-серверу.
4. **Business Manager**: app «owned»/claimed бизнесом; ассеты (ad accounts, Pages) назначены System User с нужными задачами.
5. **App Review + Business Verification** — если трогаешь ЧУЖИЕ (клиентские) ассеты.

## Точные строки разрешений

| Permission | Что даёт |
|---|---|
| `ads_management` | Создание/правка кампаний, ад-сетов, объявлений (запись). Ядро. |
| `ads_read` | Чтение кампаний + Insights (только чтение). |
| `business_management` | Управление ассетами Business Manager (ad accounts, pages, system users, шаринг). |
| `pages_show_list` | Список Страниц юзера. |
| `pages_read_engagement` | Чтение engagement Страницы (обычно рядом с лид-правами). |
| `pages_manage_metadata` | Подписка Страницы на вебхук `leadgen`. |
| `pages_manage_ads` | Управление рекламой на Страницах (лид-реклама / page-linked). |
| `leads_retrieval` | Чтение всех данных, собранных Lead-формой. |

> ⚠️ Правильные строки: **`leads_retrieval`** (не `lead_retrieval`/`leads_read`), `ads_management` (не `ads_manage`), `pages_*` (старый `manage_pages` устарел).

## Standard vs Advanced Access (переименовано 2026-05-04!)

У каждого разрешения два уровня. **Названия сменились 04.05.2026** (маппинг 1:1, не ломающий):

| Старое | Новое (актуальное) |
|---|---|
| Standard Access | **Limited Access** |
| Advanced Access | **Full Access** |

- **Limited (быв. Standard)** — выдаётся автоматически, работает **только** для юзеров/аккаунтов с ролью в твоём app (Admin/Developer/Tester/Analytics). Ок для разработки и **своих** ассетов.
- **Full (быв. Advanced)** — нужно для использования разрешения на ассетах **вне** твоего app (реальный прод/клиенты). Даётся **только после App Review**.
- `ads_management`, `business_management`, `leads_retrieval`, `pages_*` должны достичь Full Access, чтобы управлять чужими аккаунтами/читать чужие лиды.

## 🔑 Ключевая лазейка: свои ассеты не требуют App Review

Можно вызывать Marketing API против ad accounts/Pages внутри **своего** Business Manager в Development mode / с app-role юзерами, используя **System User token** — **без App Review / Full Access**. App Review + Business Verification нужны **только** когда интеграция трогает ассеты ДРУГИХ бизнесов/юзеров. Это главный фактор, определяющий, нужно ли идти через ревью.

## App Review (требует одобрения Meta)

- Подаётся: App Dashboard → App Review → Permissions and Features (по каждому разрешению).
- Meta смотрит use case, зачем каждое разрешение, пользу для юзера. Часто нужны скринкаст-демо, рабочий тест-флоу, публичная Privacy Policy URL, Data Deletion callback.
- Может отклоняться и уходить на переподачи (недели).
- Изменение (с 2026-05-04): загрузка screen-recording для сабмита access-тира больше не требуется.

## Business Verification (требует одобрения Meta)

- Верификация юр. лица в Business Manager → Security Center.
- **Обязательна** для: Full Access к `ads_management`, программного создания ad accounts, повышения квот System User.
- Отдельно от App Review. Обычно несколько рабочих дней; может застрять на несоответствии документов.
- Full Access к `ads_management` = App Review **И** Business Verification.

## Токены

| Тип | Срок | Для чего |
|---|---|---|
| Short-lived user token | ~1–2 ч | интерактив, тесты |
| Long-lived user token | ~60 дн | интерактив |
| **System User token** | **не истекает по времени** | **сервер-к-серверу (прод)** |

- System User token генерится в Business Manager → System Users → Generate Token (выбрать app + разрешения). Можно запросить истекающий (`set_token_expires_in_60_days=true`).
- **Admin** System User: создаёт system users, ad accounts, назначает права (беречь токен). **Regular** System User: только назначенные ассеты (для повседневных API-операций).
- Квоты: Limited-тир = 1 system user + 1 admin; Full-тир = 10 + 1 admin.
- Для **лидов** нужен именно **Page access token** (mintable System User'ом, который админ Страницы / имеет Leads Access).
- Обмен user→long-lived: `GET oauth/access_token?grant_type=fb_exchange_token`. Проверка токена: `GET /debug_token`.
- Обрабатывай инвалидацию (смена пароля, отзыв прав, деавторизация) — error subcode `458`/`463`/`467` → триггер re-auth.

## Marketing API Access Tier (повышенные лимиты/квоты)

Отдельный гейт от per-permission Advanced Access. Фича в App Review, поднимающая app с Dev/Limited на Standard/Full тир (выше рейт-лимиты и квоты System User).
- Переименовано 2026-05-04: фича = «Marketing API Access Tier»; тиры «Limited Access» / «Full Access».
- **Квалификация:** **500+** вызовов Marketing API за 15 дней (снижено с 1500) **И** error rate < 15% за последние 500 вызовов.
- Существующий доступ сохраняется, код менять не надо.
- ⚠️ Это **независимый** гейт от App Review: нужно И одобрение разрешений (App Review), И налёт трафика (для тира).

## Live Mode

Чтобы управлять аккаунтами в масштабе: (a) перевести app в Live Mode + (b) пройти App Review → только тогда app годен для высокого рейт-тира. В Development mode — только данные app-role юзеров и Dev-тир.

## Рейт-лимиты (BUC — Business Use Case)

`ads_management`, скользящий 1 час на ad account:
- **Dev / Limited тир:** `300 + 40 × (число активных объявлений)`.
- **Standard / Full тир:** `100000 + 40 × (число активных объявлений)`.
- Скоринг: read ≈ 1 очко, write ≈ 3 очка. Decay ~300 сек.
- **Мониторинг:** заголовок `X-Business-Use-Case-Usage` — `call_count` (%), `total_cputime` (%), `total_time` (%), `estimated_time_to_regain_access` (мин), `type`. Throttle при достижении 100%.
- Ошибка лимита: `80004` / subcode `2446079`. (Общие платформенные `4` и `17` — отдельный app-level throttle.)
- Доп.: реальтайм QPS на мутациях ≈ **100 req/s** на комбо app+ad account (medium confidence).

## Что ИМЕННО требует одобрения Meta (итог)

**Блокирующие (нужно одобрение):**
1. App Review → Full Access к `ads_management`, `business_management`, `leads_retrieval`, `pages_*` — для работы с чужими ассетами.
2. Business Verification — для Full Access к `ads_management`, программного создания ad accounts, повышения квот.
3. Перевод app в Live Mode.

**НЕ требует одобрения:**
- Создание Business-app, добавление Marketing API.
- Генерация System User token для СВОИХ ассетов.
- Вызовы API в Development mode против app-role юзеров.

## Про деньги

- **Marketing API и Graph API — бесплатны.** Нет платы за вызов, нет платного API-тира.
- Доступ гейтится **одобрением** (App Review / Business Verification), не деньгами.
- Единственная стоимость — **рекламный бюджет** (показы). Более высокий throughput = бесплатный Full-тир за налёт вызовов.
- ⚠️ У ad account должен быть привязан **funding_source** (способ оплаты), иначе `effective_status=PENDING_BILLING_INFO` и реклама не крутится.
