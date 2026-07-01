# 03 — Lead Ads: формы, вебхуки лидов, выгрузка в CRM

## Создание Instant Form (Lead-формы) программно

`POST /{page_id}/leadgen_forms` (нужен **Page access token**). Обяз.: `name`, `questions`. Возвращает `{"id":"..."}`.

### Полный список параметров создания (из SDK `page.py`)
`name`, `questions` (list<Object>), `context_card`, `thank_you_page`, `privacy_policy`, `custom_disclaimer`, `follow_up_action_url`, `locale`, `block_display_for_non_targeted_viewer`, `is_optimized_for_quality`, `is_phone_sms_verify_enabled`, `question_page_custom_headline`, `tracking_parameters`, `allow_organic_lead_retrieval`, `should_enforce_work_email`, `cover_photo` (file), `is_for_canvas`, `upload_gated_file` (file).

### `questions` — до 15 вопросов
Каждый: `key`, `label`, `type` (enum), опц. `options` (для `CUSTOM`), `inline_context`, `dependent_conditional_questions` (условная логика), `conditional_questions_group_id`.
**Типы:** `CUSTOM`, `EMAIL`, `FIRST_NAME`, `LAST_NAME`, `FULL_NAME`, `PHONE`, `WORK_EMAIL`, `WORK_PHONE_NUMBER`, `JOB_TITLE`, `COMPANY_NAME`, `CITY`, `STATE`, `PROVINCE`, `COUNTRY`, `ZIP`, `POST_CODE`, `STREET_ADDRESS`, `DOB`, `GENDER`, `RELATIONSHIP_STATUS`, `MILITARY_STATUS`, `EDUCATION_LEVEL`, `WEBSITE`, `WHATSAPP_NUMBER`, `MESSENGER`, `SLIDER`, `DATE_TIME`, `STORE_LOOKUP`, `PHONE_OTP`, `USER_PROVIDED_PHONE_NUMBER`, `JOIN_CODE`, `VIN`, `LICENSE_PLATE`, ID-типы стран (`ID_CPF`, `ID_MX_RFC`, …).

### `context_card` (интро перед вопросами)
`title`, `style` (`LIST_STYLE`|`PARAGRAPH_STYLE`), `content` (array<string>), `button_text`, `cover_photo_id`|`cover_photo`.

### `thank_you_page` (экран завершения)
`title` (обяз.), `body`, `short_message`, `button_text`, `button_description`, `business_phone_number`, `website_url`, `enable_messenger`, `gated_file`, `button_type` (`VIEW_WEBSITE`, `CALL_BUSINESS`, `MESSAGE_BUSINESS`, `DOWNLOAD`, `SCHEDULE_APPOINTMENT`, `WHATSAPP`, `NONE`, …).

### `privacy_policy` + `custom_disclaimer` (согласия / TCPA)
- `privacy_policy`: `url`, `link_text` (≤70 симв.) — **обязательно для каждой формы**.
- `custom_disclaimer` (для TCPA/согласий): `title`, `body` (`text` + `url_entities`), `checkboxes` (list: `text`, `key`, `is_required`, `is_checked_by_default`).
- ⚠️ **Отдельного `tcpa_compliance` параметра нет** — согласия реализуются через чекбоксы `custom_disclaimer` с `is_required=true`.

### Привязка формы к объявлению
Creative → `object_story_spec.link_data.call_to_action = {type: "LEAD" (или "SIGN_UP"), value: {lead_gen_form_id: <FORM_ID>}}`.
Кампания: `objective=OUTCOME_LEADS`; ад-сет: `optimization_goal=LEAD_GENERATION` + `promoted_object={page_id: <PAGE_ID>}`; `billing_event=IMPRESSIONS`.

### ⚠️ Lead Ads Terms of Service
Перед запуском лид-рекламы/сбором Страница должна принять **Lead Ads TOS** (поля Page: `leadgen_tos_accepted`, `leadgen_tos_acceptance_time`). Обычно принимается в UI Страницы, не программно.

### Читаемые поля формы (SDK `LeadgenForm`)
`id`, `name`, `status` (`ACTIVE`/`ARCHIVED`/`DELETED`/`DRAFT`), `leads_count`, `organic_leads_count`, `expired_leads_count`, `questions`, `context_card`, `thank_you_page`, `privacy_policy_url`, `locale`, `tracking_parameters`, `created_time`.
> Нюанс: GET на edge `/{page_id}/leadgen_forms` для чтения конфига помечен как «operation not supported»; реальный путь чтения — GET на узле формы/лида.

### API-capable vs Ads-Manager-first
- **Через API можно всё основное:** вопросы (вкл. `CUSTOM` и условную логику), `context_card`, `thank_you_page`, `privacy_policy`, `custom_disclaimer`, локаль, optimize-for-quality, phone/SMS OTP, tracking, + полная сборка кампании и выгрузка лидов.
- **Ads-Manager-first:** новейшие «богатые» фичи (продвинутый UI условной логики, запись на приём, gated content, rich creative), + приём Lead TOS.

---

## Выгрузка лидов в самописную CRM

Два пути, использовать **оба** (вебхук + polling для подстраховки).

### Путь 1 — Real-time (вебхук `leadgen`)
1. В App Dashboard: продукт **Webhooks** → объект **Page** → подписка на поле **`leadgen`** (Callback URL + Verify Token).
2. Установить app на конкретную Страницу:
   ```
   POST https://graph.facebook.com/v25.0/{page-id}/subscribed_apps?subscribed_fields=leadgen&access_token={page-access-token}
   ```
   (Page token от юзера с задачей **ADVERTISE** на Странице.)
3. **Верификация эндпоинта (GET-handshake):** Meta шлёт `GET` с `hub.mode=subscribe`, `hub.challenge=<int>`, `hub.verify_token`. Проверь `verify_token` и верни сырой `hub.challenge` (200, plaintext).
4. **На каждый сабмит** Meta шлёт `POST`:
   ```json
   {"object":"page","entry":[{"id":"<page_id>","time":<unix>,
     "changes":[{"field":"leadgen","value":{
       "leadgen_id":<id>,"page_id":<id>,"form_id":<id>,
       "adgroup_id":<id>,"ad_id":<id>,"created_time":<unix>}}]}]}
   ```
   ⚠️ **Данных лида в пейлоаде НЕТ** — только `leadgen_id`. Ответь `200` быстро, обрабатывай асинхронно.
5. **Проверка подписи:** заголовок **`X-Hub-Signature-256`** = `sha256=` + HMAC-SHA256(**сырое тело**, App Secret). Сравнение constant-time. (Легаси `X-Hub-Signature`/SHA1 тоже шлётся для совместимости — используй SHA256.) Официально «рекомендуется», не строго обязательно, но делай.
6. **Резолв лида:**
   ```
   GET https://graph.facebook.com/v25.0/{leadgen_id}?fields=field_data,created_time,id&access_token={page-token}
   ```
   Ответ:
   ```json
   {"id":"...","created_time":"2026-...ISO8601...",
    "field_data":[{"name":"full_name","values":["..."]},
                  {"name":"email","values":["..."]}]}
   ```
   `field_data` — массив `{name, values}`; `name` = ключ поля формы, `values` — всегда массив. Мапь `name → колонка CRM`. Ответы чекбоксов согласий — отдельно: `?fields=custom_disclaimer_responses`.

**Дополнительные поля лида** (GET `/{leadgen_id}`): `ad_id`, `ad_name`, `adset_id`, `campaign_id`, `campaign_name`, `form_id`, `is_organic`, `platform` (fb/ig), `partner_name`, `post`. Поля уровня ad/campaign требуют advertise-доступа на ad account.

### Путь 2 — Polling (добор пропущенного)
```
GET https://graph.facebook.com/v25.0/{form_id}/leads?access_token={page-token}
```
Пагинация курсором + фильтр по `created_time` (забирать только новое с последнего опроса). Список форм Страницы: `GET /{page-id}/leadgen_forms`. Это **механизм сверки** на случай простоя вебхука.

### Тестирование без трат
**Lead Ads Testing Tool** — `https://developers.facebook.com/tools/lead-ads-testing`. Выбираешь Страницу + активную форму → «Create Lead» → генерит настоящий тест-лид с плейсхолдерами, шлёт **настоящий** вебхук на Callback URL и создаёт резолвабельный `leadgen_id`. Проверяет весь пайплайн (подпись → GET → запись в CRM) без бюджета. «Delete Lead» убирает тест-лид. Чисти тест-лиды, чтобы не засорять CRM.

### Требования
- **Разрешения:** `leads_retrieval` (чтение данных лида), `pages_show_list`, `pages_read_engagement`, `pages_manage_metadata` (для подписки вебхука) / `pages_manage_ads`, `ads_management` (для ad-level полей). Все advanced-access → App Review для прода.
  - ⚠️ Расхождение в доках Meta: гайд по вебхукам называет `pages_manage_metadata`, гайд по retrieval — `pages_manage_ads`. Запроси оба, если сомневаешься.
- **Токен:** **Page access token** (не user!) — Meta рекомендует Page-токены для лидов (лучше с рейт-лимитами). Владелец токена должен иметь ADVERTISE/lead-access на Странице. Бери long-lived Page token.
- **Ретеншн 90 дней:** лид доступен к выгрузке до 90 дней с сабмита, потом удаляется. Забирай сразу; polling-добор — только в пределах 90 дней.
- **Рейт-лимит чтения лидов:** ≈ `200 × 24 × (лидов создано за последние 90 дней)` на Страницу. Мониторь `X-Business-Use-Case-Usage`. Превышение — ошибка `613`/`17`.

### Рекомендуемый пайплайн ингеста
1. App Dashboard: Webhooks → Page → поле `leadgen`, Callback URL + Verify Token.
2. `POST /{page-id}/subscribed_apps?subscribed_fields=leadgen` для каждой Страницы.
3. Эндпоинт: GET-верификация (эхо `hub.challenge`).
4. На POST: проверить `X-Hub-Signature-256` по сырому телу → вернуть 200 → положить `leadgen_id` в очередь.
5. Воркер: `GET /{leadgen_id}?fields=field_data,created_time,id` → мапнуть → **upsert по `leadgen_id`** (идемпотентно, дедап).
6. Cron-сверка: `GET /{form_id}/leads` с фильтром `created_time` — добор пропущенного (< 90 дней).
7. Проверить всё через Lead Ads Testing Tool до go-live.

---

## Варианты интеграции с CRM (3 подхода)

| Подход | Как | Когда |
|---|---|---|
| **1. Нативные CRM-коннекторы Meta** | В Meta Business Suite / Ads Manager → «Connect your CRM» (Salesforce, HubSpot, Zoho, Mailchimp, ActiveCampaign, Pipedrive…). Лиды пушатся в near-real-time без кода. | Если CRM из списка и не нужна кастомная логика |
| **2. Conversions API for CRM (Conversion Leads)** | Слать события стадий воронки обратно в Meta по 15–16-значному lead_id → реклама оптимизируется на **качество** лида, а не объём (~−15% cost/qualified lead) | **Обязательно добавить** для качества — см. ниже |
| **3. DIY вебхук/polling + middleware** | Свой пайплайн (выше). Где нет нативного коннектора — Zapier / LeadsBridge / n8n (self-host, есть нативный Facebook Lead Ads trigger node) / Make | **Наш основной путь** (самописная CRM) |

### Conversions API for CRM (Conversion Leads) — движок качества лидов
Позволяет слать down-funnel события (лид → `qualified` → `converted`) обратно, чтобы кампания оптимизировалась на качество.
- Endpoint: `POST /{dataset_id}/events` с `access_token`.
- Поля события: `event_name` (`Lead`/кастомные стадии), `event_time`, `action_source="system_generated"` (для CRM), `event_id` (дедуп), `user_data`.
- **Ключ связки:** `user_data.lead_id` = 15–16-значный Meta Lead ID (без хеша) ИЛИ хешированные PII (`em`/`ph` — SHA-256, нормализованные: email lowercase/trim, phone E.164).
- Стадии маппятся на `optimization_goal=QUALITY_LEAD`/`CONVERSION_LEADS`. Есть Event Match Quality, требование ~7-дневного сетапа/бэкфила, слать в пределах окна атрибуции.
- ⚠️ Отдельный Offline Conversions API **отключён** (~май 2025) — оффлайн/CRM-события идут через обычный Conversions API.
