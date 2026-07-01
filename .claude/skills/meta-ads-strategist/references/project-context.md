# Проектный контекст — Meliá Budva × Meta Ads

> Факты проекта, на которые опирается стратег. Источник истины по продукту —
> `melia-montage/brand/brief.md` + `brand/canon.md` (canon переопределяет brief).
> Здесь — выжимка на момент 2026-07. При расхождении сверяйся с canon.md.

## Продукт

- **Meliá Budva Hotel & Residences** — первая линия Адриатики, Бечичи–Рафаиловичи
  (Будванская ривьера, Черногория): 5★ отель (154 номера) + 136 сервисных резиденций.
- До пляжа ~10 м, 170 м фронта Blue Flag пляжа. Сдача: **Q4 2027**. Freehold, цены в EUR.
- Юниты: 5 студий (38 м²), 112×1BR (53–69 м²), 17×2BR (84–113 м²), 2×3BR (161–170 м²).
  Виды: 75 полный вид на море / 13 частичный / 48 горы. Всё turnkey, с мебелью.
- **Цены** (прайс 2025-08-29, сверяй актуальный): вход от **€263,200** (студия);
  €4,700–8,500/м²; средневзвешенно €6,705/м².
- **Оплата: 20% первый взнос** (не 10%!), остальное — беспроцентная рассрочка
  квартальными платежами до сдачи.
- Сервисный сбор: **€6.90/м²/мес**.
- Оператор: **Meliá Hotels International** (контракт 15 лет). Девелопер: SUNRAF (30+ лет).
- Инфраструктура: 4 ресторана, 3 бара, wellness-клуб 2,830 м² (2 бассейна, спа, фитнес),
  казино ~1,800 м² (**subject to regulatory approval — так и писать**), kids club,
  100 паркомест, бизнес-центр.
- **Рентная программа — опциональная**: 5 пулов, распределение по Available Rental
  Nights, сплит 70/30 (владельцы/оператор) от Net Pool Revenue. Владельческое
  использование: 15 мая–15 окт, до 4 недель/год. **Никаких гарантий доходности.**

## Сегменты аудитории (из brand/brief.md)

| # | Сегмент | Мотивация | Языки/гео | CTA |
|---|---------|-----------|-----------|-----|
| 1 | Инвесторы (int'l) | капитал в EUR, first-line дефицит, Meliá-операционка | RU (доминирует), EN, DE, HE | прайс-лист, приватная презентация, детали рентной программы |
| 2 | Семейный second home | предсказуемое лето, безопасный пляж, kids club | RU, SR, EN | семейные резиденции, презентация |
| 3 | Wellness / longevity | спа, климат, круглогодичная инфраструктура | EN, DE, PL | Sun Wellness Club, опции |
| 4 | Budva energy / lifestyle | казино, рестораны, Старый город 4 км | RU, SR | презентация, доступные юниты |
| 5 | Digital nomads / long-stay | связь, сервис, консьерж | EN, RU | опции покупки, 1BR |
| 6 | Брокеры/агенты | факты, комиссия, юридика | EN, RU | agent pack |

Согласованные языки кампаний: **RU, SR, EN, DE, PL, HE** — одна лид-форма на язык.
Копирайт: только перевод/транскреация из англ. брифа, не авто-перевод.

## Жёсткие гардрейлы контента (без исключений)

НЕЛЬЗЯ в рекламе:
- Гарантированная доходность/заполняемость/ADR/рост цены; "passive income guaranteed";
  конкретные % доходности (4–6% — только internal).
- "Private beach" как эксклюзив (безопасно: "dedicated Blue Flag beach zone").
- Казино как работающее (только "subject to regulatory approval").
- BREEAM "certified" (только "targeting certification").
- Точные даты сдачи кроме канона "Q4 2027"; времена в пути до аэропортов;
  "280 солнечных дней"; "15% flat tax"; "first international 5-star..." (требует апрува).
- MeliáRewards-бонусы, если акция не активна прямо сейчас.

ОБЯЗАТЕЛЬНО: цены "indicative / по актуальному прайсу"; рентная программа —
"optional, returns not guaranteed"; язык инвест-нарратива — "projected", "designed to",
"professionally managed".

## Поверхность инструментов (facebook-ads, статус 2026-07)

Аккаунт: `act_776404808314031` ("Melia Budva 1", EUR, ACTIVE). Page:
"5-Star Melia Private Residences Budva" (`723322257538609`). System User token,
App Review не нужен. Кампании собираются программно (Marketing API v25).

**CLI `fb` (работает):** `auth-bootstrap`, `creative upload <path>` (image_hash/video_id,
кэш по path+mtime+size), `campaign create` (Campaign OUTCOME_LEADS → AdSet
LEAD_GENERATION, всегда PAUSED, `validate_only=True` по умолчанию), `leads poll`,
`leads test`, `conversions setup-datasets` / `conversions drain-outbox` (CAPI,
phase 2 реализован). Стаб (phase 3): `sync` (insights).

**MCP `kvadra-facebook-ads`:** мутации гейтованы `dry_run=True` + `FB_ALLOW_MUTATIONS`
(`upload_creative`, `create_lead_campaign`, `pause_campaign`, `resume_campaign`,
`update_campaign_budget`). Аналитика (`account_summary`, `campaign_perf`, `ad_status`,
`budget_pacing`, `conversion_funnel`, `analyze_lead_quality`, `leads_by_campaign`) и
планирование (`interest_search`, `audience_estimate`) — phase 3, пока стабы: до их
готовности инсайты снимаем через Graph API / Ads Manager вручную.

**Worker (Hetzner, systemd `fb-worker`):** `lead_resolve` (LISTEN meta_leadgen →
resolve → CRM ingest), `lead_poll` (сверка <90 дней), `capi_drain` (outbox → CAPI,
ключ **строго Meta lead_id**); стабы: `perf_pull`, `moderation`, `pacing`.

**Состояние на 2026-07-02:** все три пайплайна работают — A (сборка кампаний)
проверен вживую (EN-кампания `120250357368240233`, PAUSED, ревью пройдено),
B (лиды) автономен (fb-worker задеплоен на боксе, systemd; webhook→CRM ~3 сек),
C (CAPI) live и доказан (dataset `1322604432905922`, 6 событий). **На Page уже
крутятся ~5 живых кампаний июня 2026** (созданы до сервиса, напр. "Serbia Lead
Cities Campaign June 2026", форма "SR Lead Form 12062026") — page-level webhook
ловит лиды со ВСЕХ форм Page; первый реальный лид: CRM #4324 (+381, SR).
Наследованные кампании — часть текущей структуры аккаунта: при планировании
инвентаризуй их первыми (нейминг у них вне нашей конвенции).

## Money safety (нарушать нельзя)

1. Всё создаётся **PAUSED**; активация — отдельное осознанное действие.
2. `validate_only` перед каждым реальным create.
3. Account-level `spend_cap` = kill-switch — выставлен ДО любых трат.
4. Идемпотентность по `spec_hash` (meta.campaign_external_map) — не плодить дубли.
5. Мутации через MCP: сначала `dry_run=true`, показать результат, потом
   `dry_run=false` + `confirm="yes"` (и только при `FB_ALLOW_MUTATIONS=1`).
6. Кампания: `is_adset_budget_sharing_enabled=false` (ABO); адсет:
   `bid_strategy=LOWEST_COST_WITHOUT_CAP` + явный `targeting_automation.advantage_audience`;
   CTA `SIGN_UP` (не "LEAD"); видео-креативу нужен thumbnail; форме — `follow_up_action_url`.

## CAPI-таксономия (CRM lifecycle → Meta event, conversions/taxonomy.py)

```
lifecycle_qualified → lead_qualified          (€20)
lifecycle_offer     → lead_offer_sent         (€30)
lifecycle_meeting   → lead_meeting_scheduled  (€50)
lifecycle_deposit   → lead_deposit_paid       (реальная сумма)
lifecycle_contract  → lead_contract_signed    (реальная сумма)
lifecycle_paid      → lead_paid               (реальная сумма)
SKIP: lead_submitted (сабмит формы Meta уже видит), lifecycle_negotiation
```
Сверяй с `src/meta_ads/conversions/taxonomy.py` — таксономия живёт там.

**Инвариант:** событие уходит в CAPI только при наличии Meta `lead_id`
(v_leads_meta.meta_lead_id). Никогда не определять "наш ли лид" по хешу PII.

## Креативный конвейер

- Студия: `melia-montage` (Remotion + ElevenLabs v3 + HeyGen). Финалы →
  `OneDrive\Desktop\Melia Reels\` (сейчас: `Final Basic` — EN/PL/SR × 1x1/4x5/9x16).
- Копибанк: `melia-montage/brand/copy/` (reels EN/RU), 70+ заголовков.
- 7 креативных столпов: first-line ownership, Meliá home, smart investment, wellness,
  family, Budva energy, turnkey quality. 8 визуальных тем в visual-style.md.
- Лид-формы: `is_optimized_for_quality=true`, SMS-OTP (`is_phone_sms_verify_enabled`),
  privacy_policy (kvadra.me/privacy), consent-чекбоксы, `follow_up_action_url`.

## Экономика (рамка для планирования)

Чек ~€263k–1.5M, маржинальная стоимость сделки высокая → даже 1 сделка окупает
годы рекламы. Цикл сделки длинный (месяцы). Бюджеты: сотни–низкие тысячи EUR/мес
на рынок. Это значит: оптимизируем на **качество лида** (cost per qualified lead,
cost per meeting), а не на сырой CPL; терпимость к дорогим лидам высокая, к
мусорным — нулевая (время сейлзов — узкое место).
