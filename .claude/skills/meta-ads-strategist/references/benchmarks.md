# Рыночные бенчмарки 2025–2026 — Meta lead gen для real estate / off-plan

> Верифицированный веб-ресёрч (июль 2026). Источники указаны доменами; пометки
> уверенности: **[high] / [medium] / [low]**, одноисточниковые данные —
> **(directional)**. Проектные факты (продукт, сегменты, гардрейлы, экономика) —
> в `project-context.md`, здесь их не дублируем.
>
> Зоны соседних файлов: методика медиаплана и бюджетов — `planning.md`;
> какие метрики и где смотреть — `tracking.md`; циклы обучения и тестов —
> `learning.md`; креативная стратегия — `creative.md`; модерация и правила
> площадки — `policy.md`; чек-лист запуска — `launch.md`.

## 1. Как пользоваться бенчмарками

- Это **диапазоны для калибровки ожиданий и sanity-check**, а не цели (targets)
  и не KPI. Цель кампании выводится из unit-экономики (см. §5 и `planning.md`),
  а бенчмарк отвечает на вопрос «наш результат вообще правдоподобен?».
- Разброс между источниками велик и объясняется методологией (медианы vs
  средние, определение «лида», US-heavy выборки). Никогда не усредняй два
  источника в «одно число» — держи диапазон целиком.
- **Собственные данные всегда важнее рыночных.** Рыночный диапазон нужен ровно
  до момента, пока наш факт статистически не созрел (пороги зрелости — §7).
- Правило замены: как только по метрике накоплен объём из §7, рыночная колонка
  становится справочной, а решения принимаются по колонке «наш факт».
- Почти все цифры ниже — **до-Q3-2025 или US/UAE-центричные**. Черногория не
  покрыта ни одним крупным датасетом; ближайшие прокси — Сербия (по CPM) и UAE
  off-plan (по модели international-покупателя).

## 2. CPL по регионам и типам

### 2.1 Blended-бенчмарки (US-heavy, глобальные)

| Датасет | CPL real estate | Контекст | Уверенность |
|---|---|---|---|
| LocaliQ/WordStream 2025 (~1,000+ US-кампаний, апр 2024–июн 2025) | **$16.61** (leads-objective) | vs $27.66 all-industry (рост с $22.87 годом ранее) | [high] wordstream.com — цифры подтверждены fact-check |
| SuperAds ($3B spend, июл 2025–июн 2026, медианы) | **~$30.20** в среднем | vs $45.59 global baseline (−34%); рост ~80% за 13 мес: $23.13 (июн 2025) → пик $41.58 (июн 2026); сезонный минимум $15.74 (ноя 2025) | [high] superads.ai |

Разрыв $16.61 vs $30.20 — методология и определение лида; оба числа —
US-heavy blends, **не** локальные EU-значения. WordStream также отметил рост
real estate CPC на ~40% YoY — один из максимальных по вертикалям [high].

### 2.2 UAE — ближайший прокси international off-plan / branded residences

| Метрика | Значение | Уверенность |
|---|---|---|
| CPL real estate UAE (SuperAds) | **$20.70** vs $37.35 global (~45% дешевле) | [medium] superads.ai |
| Meta lead-form CPL, Dubai (ThePrimeAds 2026) | AED 30–300 (**~$8–80**) | [medium] theprimeads.com (agency-reported) |
| Off-plan digital leads, Dubai | AED 30–120 (**~$8–33**) | [medium] theprimeads.com |
| Google Search CPL для сравнения | AED 450–900 | [medium] theprimeads.com |
| Self-generated leads → sale | 5–10% (vs 1–3% у купленных) | [medium] theprimeads.com |

80%+ сделок в Дубае — international buyers, т.е. это ровно наша модель
diaspora/source-market таргетинга. Нижние границы предполагают
volume-оптимизированные instant forms.

### 2.3 Ориентировочные CPL-тиры по нашим рынкам (производные от CPM, §3.2)

| Кластер рынков | Instant-form CPL, ориентир | Статус |
|---|---|---|
| Балканы / RU-диаспора в дешёвых гео | **€5–15** | производное из CPM-данных (directional) |
| Польша | **€10–25** | производное (directional) |
| DE / UK / IL | **€25–60+** | производное (directional) |

Это не измеренные бенчмарки, а расчёт из CPM-реальности (§3.2): при равном
креативе одинаковый бюджет покупает в 2–4 раза разный охват. CPL-target
задаётся **на рынок**, не на аккаунт; оценка рынка — по cost per
CRM-qualified lead, не по сырому CPL.

### 2.4 Instant form vs landing page

| Параметр | Instant form | Landing page | Уверенность |
|---|---|---|---|
| CPL | на **30–50% ниже** | база | [high] stackmatix.com + LeadSync, Stape, GoAdFuel (консенсус нескольких независимых источников) |
| CVR | **в 2–3 раза выше** (особенно mobile) | база | [high] там же |
| Качество лида | ниже (больше мусора) | выше | [high] там же |

Консенсус-паттерн 2025–2026 для high-ticket property: instant forms на TOFU
с квалифицирующим трением (Higher Intent тип формы, 1–3 качественных вопроса,
open-text вместо pre-filled) + landing page / WhatsApp на BOFU/ретаргетинге.
WhatsApp click-to-message лиды в сопоставимых рынках — **$22–38/лид**,
самоселекция на более высокий intent [medium] brandedresi.com (directional).

## 3. CTR / CPM / CVR

### 3.1 CTR (LocaliQ/WordStream 2025, US)

| Тип кампании | CTR real estate | Примечание | Уверенность |
|---|---|---|---|
| Leads-objective | **3.7%** | 2-е место среди индустрий (1-е — Arts & Entertainment 3.92%; поправка fact-check) | [high] wordstream.com |
| Traffic | **~2.75%** | высоко-вовлекающая вертикаль | [medium] wordstream.com |

Важно: интерес к недвижимости широкий, высокий CTR ≠ intent — квалификация
будет заметно ниже качества клика. Практический health-check из ресёрча:
устойчивый CTR **< ~1.5%** на 4:5/9:16 видео о недвижимости пост-Andromeda —
обычно проблема креатива, не аудитории (directional).

### 3.2 CPM по нашим рынкам (2026-проекции из данных конца 2025)

| Рынок | CPM | CPC | Уверенность |
|---|---|---|---|
| Сербия | ~$2.77 | — | [medium] Lebesgue |
| Балканы / Tier-3 в целом | $1.50–4 | — | [high] adamigo.ai |
| Польша | $5.50 | $0.75 | [medium] adamigo.ai |
| Испания | $5.80 | $0.85 | [medium] adamigo.ai |
| Португалия | $6.10 | $0.90 | [medium] adamigo.ai |
| UAE | $6.50 | $1.40 | [medium] adamigo.ai |
| Израиль | ~$7.48 (Tier-2 band $6.50–12) | — | [medium] Lebesgue / adjacent datasets |
| Германия | $10.05 | $1.45 | [medium] adamigo.ai |
| UK | $10.31 | $1.95 | [medium] adamigo.ai |
| Черногория | **нет в датасетах**; ожидать уровень Сербии | [low] — прокси |

Следствие (задокументировано): не пулить в один ad set страны с разницей CPM
> ~30% — алгоритм зальёт бюджет в дешёвое гео. Детали структуры — `planning.md`.

### 3.3 CVR и режим Andromeda (rollout завершён ~окт 2025)

Прямых CVR-бенчмарков (form completion rate и т.п.) ресёрч не дал — честно
мало данных. Что есть:

| Факт | Значение | Уверенность |
|---|---|---|
| 1 ad set × ~25 разных креативов vs структура 5×5 | **+17% конверсий / −16% cost** | [high, но practitioner-reported — магнитуды directional] segwise.ai |
| Advantage+ creative | +22% ROAS (тесты Meta) | [high, practitioner-reported] segwise.ai |
| Окно ad fatigue | сжалось с 6+ недель до **2–4 недель** | [high] segwise.ai |
| Сигналы усталости креатива | CTR ↓ >10% или CPA ↑ >15% week-over-week | [high, directional] segwise.ai |
| Порог похожести креативов | similarity > ~60% → suppression | [high, practitioner-reported] segwise.ai |
| Placement/daypart для property-инвесторов | **достоверных бенчмарков НЕТ** (negative finding); подтверждено только: mobile-доминирование, WhatsApp/IG DM как канал связи, «социалки = discovery, порталы = search» | [medium] floridarealtors.org |

Дефолт из ресёрча: Advantage+ placements + mobile-first 9:16/4:5; ручные
ограничения placement/schedule пост-Andromeda режут delivery. Креативные
следствия — `creative.md`, циклы тестов — `learning.md`.

## 4. Воронка off-plan / branded residences / second homes

### 4.1 Поэтапные конверсии

| Этап | Диапазон | Источник / уверенность |
|---|---|---|
| Lead → qualified | **25–35%** | [high] conversionrealtor.com (отчёт янв 2026, NAR + platform data) |
| Cost per qualified lead (US Meta) | **$35–65** | [medium] get-ryze.ai |
| Lead → appointment (среднее по индустрии) | **10–15%** (top producers 25–30%) | [high] conversionrealtor.com |
| Lead → showing/viewing «хорошо» | **18–25%** | [medium] get-ryze.ai |
| Qualified → appointment/viewing | **30–50%** | [high] conversionrealtor.com |
| Appointment → sale (планировочная цепочка) | **10–20%** | [high] conversionrealtor.com |
| Showing → offer | **35–50%** | [medium] get-ryze.ai |
| Offer → close | **60–80%** | [medium] get-ryze.ai |
| Off-plan: engaged prospect на встрече/в display suite → sale | **20–30%**, до ~50% с интерактивной 3D-визуализацией | [medium] theurbandeveloper.com (trade-press, механика evergreen) |

### 4.2 Композитная lead → sale и «сколько лидов на сделку»

| Тип лида | Lead → sale | Лидов на 1 сделку | Уверенность |
|---|---|---|---|
| Сырой internet-лид (raw) | **0.5–1.5%** | **~70–200** | [medium] Follow Up Boss / Ylopo / NAR via get-ryze.ai |
| Google/Facebook ads leads | **1–4%** | 25–100 | [high] conversionrealtor.com |
| Social media leads | 2–5% | 20–50 | [high] conversionrealtor.com |
| Portal leads | 1–3% | 33–100 | [high] conversionrealtor.com |
| Хорошо отработанные self-generated | **2–5%+** | 20–50 | [medium] get-ryze.ai |
| Планировочное допущение для холодного international off-plan | **~1–2%** | 50–100 | [high] conversionrealtor.com (рекомендация отчёта) |

Structured teams закрывают 5–10% vs 1.5–3% у solo — CRM-дисциплина примерно
удваивает композит [high]. Facebook-лиды в отчёте явно названы
«interruption-based, not intent-based». Воронка off-plan **бимодальна**:
лид почти ничего не стоит, пока не стал booked conversation — управлять надо
шагом lead → appointment.

### 4.3 Длина цикла и nurture

| Факт | Значение | Уверенность |
|---|---|---|
| Foreign buyer, active search → close (US) | ~5–6 мес | [medium] homeabroadinc.com |
| То же, UK | ~7 мес | [medium] homeabroadinc.com |
| Lead → contract (domestic US, оптимистичная граница) | 45–90 дней | [medium] get-ryze.ai |
| Luxury/branded-residence nurture | **до 20–25 касаний за месяцы**; nurtured-лиды: покупки ~+47% крупнее, +50% sales-ready лидов при −33% cost | [medium] Ylopo/Luxury Presence/Studeo |
| Meta-лиды, Dubai: первые сделки | 1–4 недели ТОЛЬКО для горячих in-market; social-origin отношения зреют **12–18 мес** | [medium] theprimeads.com |
| Speed-to-lead | ответ < 5 минут → квалификация **в 21 раз** вероятнее; **>60%** branded-residence проектов вообще не делают follow-up (mystery-shopper) | [medium] brandedresi.com / theprimeads.com |

Следствие для измерения: когорты 6–12 месяцев, не 30-дневные окна — иначе
системно убиваются лучшие prospecting-кампании. Как это отслеживать —
`tracking.md`.

## 5. Экономика девелопера и наш чек €263k+

### 5.1 Отраслевые нормы

| Норма | Значение | Уверенность |
|---|---|---|
| Маркетинг от projected sellout (US, master-planned) | **1–1.5%** | [medium] Miles Brand via dsemotion.com |
| Маркетинг от GDV (UK/EU new developments) | **до ~2%** (2% — стандартный планировочный якорь) | [high] dsemotion.com |
| Digital/paid в общем маркетинг-бюджете | **30–60%** | [high] dsemotion.com |
| Advertising/promotion от бюджета проекта | 3–5% | [medium] developer cost-structure refs |
| Sales commissions сверху | 1–3% | [medium] там же |
| Cost per sale из paid media, юнит €200k | **€2–6k** — внутри нормы (1–3% цены) | [medium] dsemotion.com |
| Референс на €200k юнит | €2,000–4,000 маркетинга на проданный юнит, из них ~€1,200–2,400 допустимый paid media cost per sale | [high] dsemotion.com |

### 5.2 Обратная математика для нашего входного чека €263,200 (коротко)

Формула из ресёрча [high, davechaffey.com]:
`допустимый CPL = (допустимый marketing cost per sale) × (lead-to-sale rate)`.
Референсный расчёт источника для €200k юнита: 1.5% → €3,000/сделка, ~2/3 в
paid → €2,000; CPL ceiling €20 (при 1% lead→sale) / €40 (2%) / €60 (3%);
CPQL ceiling при ~30% квалификации → **€65–130, до ~200**.

Та же формула на наш чек (арифметика, не бенчмарк):

| Параметр | При 1.5% от чека | При 2% от чека |
|---|---|---|
| Marketing allowance / сделка | ~€3,950 | ~€5,260 |
| Paid media allowance (~2/3) | ~€2,630 | ~€3,510 |
| CPL ceiling при lead→sale 1% | ~€26 | ~€35 |
| CPL ceiling при lead→sale 2% | ~€53 | ~€70 |
| CPQL ceiling (квалификация ~30%) | ~€88–175 | ~€117–234 |

Считать **на рынок** (диаспорные RU/SR-лиды квалифицируются и закрываются
лучше холодных DE/UK → выдерживают более высокий ceiling). Средний чек
портфеля выше входного (€263k — минимум, юниты до €1.5M) — реальные ceilings
консервативны. Полная методика ceilings, floors и аллокации — `planning.md`.
Вывод ресёрча: при наших сотнях–низких тысячах EUR/мес бюджет консервативен
относительно норм — ограничение не в % от выручки, а в скорости обработки
лидов и объёме креативного конвейера.

## 6. Сезонность international / second-home спроса

| Окно | Что происходит | Уверенность |
|---|---|---|
| Конец декабря — февраль | Rightmove: пик трафика/enquiries с Boxing Day и весь январь; Kyero (91M+ визитов за 5 лет): пик поиска overseas-жилья **в конце февраля** (post-winter planning) | [high] propertyinvestortoday.co.uk; данные Kyero до 2023, но структурные |
| Середина августа — сентябрь | Kyero: второй пик **в конце августа** (вернувшиеся отпускники); для Будвы совпадает с людьми, только что посетившими Черногорию → окно ретаргетинга летних engagers | [high] |
| Воскресенье | Сильнейший день недели по поиску (Kyero) | [high] |
| Ноябрь | Худшее окно: глобальный медианный CPM $25.22 (ноя 2025) vs $15.74 (янв 2026, Lebesgue) при слабом property-intent — «Q4 вдвойне плох» | [high] |
| Март–июнь | Базовый уровень | [medium] |

Ресёрч-рекомендация: up-weight ~30% на конец дек–фев, ~20% на середину
авг–сен, down-weight ноябрь (реализация — `planning.md`).

**Честная оговорка о противоречии:** SuperAds (US-heavy) фиксирует сезонный
*минимум* real estate CPL в ноябре 2025 ($15.74) и пик в июне 2026 — это не
совпадает с EU-паттерном intent'а по Kyero/Rightmove. US-blended CPL-сезонность
≠ сезонность европейского overseas-спроса; для наших рынков опираться на
Kyero/Rightmove до появления собственных данных.

**Контекст спроса Черногории** [low; одноисточниковая trade-press 2026,
montenegrobusiness.eu — валидировать по CRM-гео]: спрос диверсифицируется за
пределы традиционной RU-базы; быстрорастущие сегменты — US remote-work
покупатели («work-from-Europe» арбитраж) и азиатские HNWI (почти исключительно
branded residences); Будва позиционируется как liquidity/rental-yield рынок.
Следствие: EN-кампании под US/remote-work угол — потенциальный вектор
расширения (сейчас не в шести согласованных языках).

## 7. Таблица «наши якоря» (заготовка — обновлять из CRM/insights)

Правило зрелости данных: наш факт **заменяет** рыночный диапазон, когда
достигнут порог объёма из колонки «порог» (эвристики, привязанные к якорям
ресёрча: ~50 optimization events/ad set/неделя — порог обучения Meta;
10–15 лидов/мес — минимальная закупка на рынок; sale-когорты зреют месяцы 2–8).
До порога наш факт — «ранний сигнал», сверяемый с рыночной колонкой.

| Метрика | Рынок 2026 (якорь) | Наш факт | Дата обновления | Источник факта | Порог достоверности |
|---|---|---|---|---|---|
| CPL instant form, Балканы/RU-диаспора | €5–15 (directional) | — | — | Ads Manager / `campaign_perf` | ≥30–50 лидов на рынок |
| CPL instant form, PL | €10–25 (directional) | — | — | Ads Manager | ≥30–50 лидов |
| CPL instant form, DE/UK/IL | €25–60+ (directional) | — | — | Ads Manager | ≥30–50 лидов |
| CTR leads-кампаний | ~3.7% (US) | — | — | Ads Manager | ≥3–4 недели ротации креативов |
| CPM по рынку | см. §3.2 | — | — | Ads Manager | ≥1–2 недели delivery без Learning Limited |
| Lead → qualified | 25–35% | — | — | CRM lifecycle (`analyze_lead_quality`) | ≥50 лидов, прошедших разбор |
| CPQL | $35–65 (US) / ceiling §5.2 | — | — | CRM + spend | ≥15–20 qualified |
| Qualified → meeting | 30–50% | — | — | CRM lifecycle_meeting | ≥20 qualified в зрелых когортах (2+ мес) |
| Meeting → sale | 10–30% (off-plan до ~50%) | — | — | CRM deposit/contract | ≥10 meetings; когорты 6–12 мес |
| Lead → sale композит | ~1–2% (допущение) | — | — | CRM cohort-отчёт | ≥100–200 лидов в когортах старше 6 мес |
| Лидов на 1 сделку | 50–200 | — | — | производное | — (следует из строки выше) |
| Длина цикла lead → deposit | 5–7+ мес | — | — | CRM timestamps | ≥5 сделок |
| Speed-to-lead (median first touch) | <5 мин — цель | — | — | CRM/respond.io | сразу (операционная метрика) |
| Доля qualified по языку/рынку | нет рыночного | — | — | CRM гео/язык | ≥20 qualified на срез |

Процедура: пересматривать таблицу **ежемесячно** вместе с когортным прогнозом
(методика — `planning.md`, источники данных — `tracking.md`); при заполнении
«наш факт» датировать и указывать объём выборки в скобках. Устаревание
рыночной колонки: числа собраны в июле 2026, пересобрать ресёрч через
~12 месяцев или при явном сдвиге режима площадки (аналог Andromeda).
