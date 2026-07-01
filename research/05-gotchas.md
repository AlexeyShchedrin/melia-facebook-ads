# 05 — Подводные камни и пробелы (что всплывёт при разработке)

> Из блока «completeness critic». Отранжировано по тому, насколько вероятно застопорит первую рабочую версию.

## 🔴 Топ-4 самых блокирующих

### 1. Conversions API for CRM — движок КАЧЕСТВА лидов (недооценён)
Без обратной связи о качестве лид-реклама оптимизируется на **объём мусорных лидов**. Нужно реализовать как полноценный компонент:
- `POST /{dataset_id}/events`, поля: `event_name` (`Lead`/кастомные стадии `qualified`/`converted`), `event_time`, `action_source="system_generated"`, `event_id` (дедуп).
- `user_data` по 15–16-значному `lead_id` (без хеша) ИЛИ хешированные PII: `em`/`ph` = **SHA-256** нормализованных (email lowercase/trim, phone E.164).
- Маппинг стадий на `optimization_goal=QUALITY_LEAD`/`CONVERSION_LEADS`, Event Match Quality, ~7 дней сетапа, слать в окне атрибуции.
Подробнее — [03-lead-ads-crm.md](03-lead-ads-crm.md#conversions-api-for-crm-conversion-leads--движок-качества-лидов).

### 2. Деньги: funding, spend caps, dev-safety
- API бесплатный, но у ad account должен быть **funding_source**, иначе `PENDING_BILLING_INFO`.
- **Баг с `status=ACTIVE` тратит реальные деньги мгновенно.** Защита:
  - account-level `spend_cap` как hard kill-switch;
  - создавать всё в `PAUSED`;
  - `execution_options=['validate_only']` — «сухой прогон» без создания объектов (безопасно тестировать пейлоады);
  - помнить про минимальный дневной бюджет ад-сета (зависит от `optimization_goal`/валюты);
  - `end_time`/`lifetime_budget` как потолок трат.
- Валюта и таймзона фиксируются при создании ad account и влияют на всю математику бюджета (минорные единицы).
- **Настоящей «песочницы с фейковыми деньгами» нет** — тест-аккаунты есть, но реальная доставка стоит реальных денег.

### 3. Модерация / реджекты как рабочий цикл
Объявления уходят в `PENDING_REVIEW` (минуты–24 ч), могут словить `DISAPPROVED`. Нужна машина состояний:
- читать причины: поля Ad `ad_review_feedback`, `issues_info` (`error_summary`/`error_message`/`level`/`error_code`);
- поллить завершение ревью;
- слать апелляции/request review;
- **правка объекта сбрасывает в `PENDING_REVIEW`**;
- account-level policy strikes могут отключить весь аккаунт.

### 4. «Локально» вебхуки принять НЕЛЬЗЯ
Callback для лидов = публичный **HTTPS** URL с валидным TLS. Локальный инструмент требует тоннель (ngrok / Cloudflare Tunnel) или маленький публичный релей. Альтернатива — жить только на **polling**.
- Доставка **at-least-once** → будут дубли `leadgen_id` → дедап идемпотентно.
- Порядок доставки не гарантирован; провалы ретраятся и дропаются → именно поэтому нужен polling-сверщик.
- Миграция webhooks mTLS-сертификатов на Meta CA (~март 2026) — обнови trust-store.

## 🟠 Прочие важные

### 5. FB vs Instagram и per-placement специфика
- Для IG-плейсментов нужен `instagram_user_id`/`instagram_actor_id` (или связанный IG на Странице), иначе на IG **молча не крутится**.
- Разные плейсменты — разные соотношения (1:1/4:5 feed, 9:16 Stories/Reels); один `image_hash` может кропаться/отклоняться per placement.
- `asset_feed_spec` / placement_asset_customization — креатив под каждый плейсмент.
- Ручные плейсменты + несовместимый креатив = delivery 0 **без явной ошибки**.

### 6. Insights API — цикл обратной связи для «автоматизации»
Любая автоматизация, что оптимизирует, должна читать перформанс. Не забыть: async-паттерн (`report_run_id` → поллинг), каталог метрик, разбивки и лимиты комбинаций, `date_preset`/`time_range`/`time_increment`, окна атрибуции, лаг свежести данных. Детали — [02-marketing-api.md](02-marketing-api.md#инсайты--метрики-следить-за-результатами).

### 7. Токен-lifecycle
Минтинг long-lived System User token, инвалидация (смена пароля/отзыв/деавторизация → subcode `458`/`463`/`467` → re-auth), `GET /debug_token` для проверки expiry/scopes, обмен `grant_type=fb_exchange_token`, шифрованное хранение (не в исходниках). Битый токен = тихий полный простой.

### 8. Идемпотентность и таксономия ошибок
- **У Meta НЕТ idempotency-key** → повтор `create` создаёт дубль. Свой дедап (по name/tracking).
- Различать transient (`4`/`17`/`80004`, `is_transient=true`, HTTP 500/503) vs permanent (`100`/`200`, невалидные параметры).
- Exponential backoff по `estimated_time_to_regain_access`.
- В batch-запросах у каждого саб-запроса свой статус (partial failure).
- Коды, встречающиеся: `17`, `613`, `80004`, `2446079`, `1363037`, `458`.

### 9. PII / GDPR / CCPA
- Лиды = персональные данные. Meta требует **Data Deletion callback** + публичную **Privacy Policy URL** (оба — пререквизиты App Review).
- GDPR/CCPA обязанности: правовое основание, лимиты хранения, право на удаление (зеркалит 90-дневное окно Meta).
- При отправке PII в Conversions API — **SHA-256** с нормализацией (email lowercase/trim, phone E.164).

### 10. Мульти-аккаунт / агентство (multi-tenant)
Если управляешь >1 бизнесом (это форсит полный App Review): owned vs client ad accounts, агентский доступ через Business Manager, per-asset назначение задач System User, partner/business handshakes для доступа к клиентскому `act_<id>` и Странице, каждая клиентская Страница отдельно принимает Lead TOS и даёт lead access.

### 11. Advantage+ ограничение + матрица совместимости
- С v25.0 **нельзя создавать через API** Advantage+ Shopping/App кампании → только обычные/manual.
- Матрица `objective ↔ optimization_goal ↔ billing_event ↔ promoted_object` валидируется сервером и меняется. Частый источник 400. Стратегия: `execution_options=validate_only` или ловить «Invalid optimization goal for objective» и маппить.

### 12. Качество лидов на уровне формы
Стратегические ручки: `is_optimized_for_quality` (higher-intent форма — меньше, но лучше лидов) vs volume; `is_phone_sms_verify_enabled` (OTP против фейк-номеров); prefill (Meta предзаполняет PII → выше доля фейков/опечаток); кастомные вопросы снижают prefill-фрод. Прямо влияет на долю мусора в CRM.

## Build vs Buy (стоит ли вообще писать самому)

| Задача | Готовые альтернативы |
|---|---|
| Автоматизация ad ops (правила над тем же API) | **Revealbot**, **Madgicx** |
| Лиды → CRM | **n8n** (self-host, нативный Facebook Lead Ads trigger node — снимает часть бремени App Review), Make, Zapier, LeadsBridge, Stape |
| Отчётность/инсайты | Supermetrics, Windsor.ai, Coupler.io |

Ключевой трейд-офф: middleware часто **берёт на себя App Review / токены** (выступает app-of-record), экономя недели одобрений. Для самописной CRM разумный гибрид: писать самим только то, что уникально (сама CRM + бизнес-логика), а приём лидов на старте можно снять через n8n.
