# 02 — Meta Marketing API: кампании, таргетинг, креативы, инсайты, управление

> База: `https://graph.facebook.com/v25.0/...` — **всегда пиши версию явно** в пути (без версии попадёшь на самую старую живую).
> Enum-значения ниже взяты из официального `facebook-python-business-sdk` (main), который кодогенерится из спеки API и зеркалит строковые константы 1:1.

## Объектная модель

Иерархия под рекламным аккаунтом `act_<AD_ACCOUNT_ID>`:

```
Ad Account (act_<ID>)
  └─ Campaign        (внутр. тип 'campaign' / 'ad_campaign_group') — objective, buying_type, (CBO) бюджет+bid_strategy
       └─ Ad Set     (внутр. тип 'adcampaign' — путается!) — optimization_goal, billing_event, targeting, бюджет(ABO), promoted_object
            └─ Ad    (внутр. тип 'adgroup') — связывает Ad Set + AdCreative
       AdCreative    — object_story_spec (визуал/копия), ссылается из Ad
```
Одно Ad → один Ad Set + один AdCreative. Один Ad Set → одна Campaign.

## Версии API

- Актуальная: **v25.0** (2026-02-18). Старше живые: v24.0 (2025-10-08), v23.0 (2025-05-29), v22.0 (2025-01-21), v21.0 (2024-10-02).
- v20.0 истекает 2026-09-24; v19.0 — 2026-05-21; v18.0 истекла 2026-01-26.
- Пинай версию явно, планируй регулярный бамп (~раз в квартал новая, депрекейт ~через 2 года).

---

## Создание кампании

`POST /act_<AD_ACCOUNT_ID>/campaigns`

Параметры: `name`, `objective`, `status`, **`special_ad_categories`** (ОБЯЗАТЕЛЬНО — иначе 400; для обычной рекламы `[]` или `['NONE']`), `special_ad_category_country`, `buying_type` (default `AUCTION`), `bid_strategy`, `daily_budget`/`lifetime_budget` (в минорных единицах = центах; на уровне кампании = включает CBO), `spend_cap`, `promoted_object`, `is_skadnetwork_attribution`, `execution_options`.

Ответ: `{"id":"<campaign_id>"}`.

```bash
curl -X POST \
  -F 'name=My Leads Campaign' \
  -F 'objective=OUTCOME_LEADS' \
  -F 'status=PAUSED' \
  -F 'special_ad_categories=[]' \
  -F 'access_token=<TOKEN>' \
  https://graph.facebook.com/v25.0/act_<AD_ACCOUNT_ID>/campaigns
```

### `objective` (ODAX — используй для новых кампаний)
`OUTCOME_AWARENESS`, `OUTCOME_TRAFFIC`, `OUTCOME_ENGAGEMENT`, `OUTCOME_LEADS`, `OUTCOME_APP_PROMOTION`, `OUTCOME_SALES`.
(Легаси в enum, но депрекейт для новых: `LEAD_GENERATION`, `CONVERSIONS`, `LINK_CLICKS`, `REACH`, `BRAND_AWARENESS`, `POST_ENGAGEMENT`, `VIDEO_VIEWS`, `APP_INSTALLS`, `MESSAGES`, `PRODUCT_CATALOG_SALES`, …)

### `status` / `effective_status`
- `status` (задаётся): `ACTIVE`, `PAUSED`, `ARCHIVED`, `DELETED`.
- `effective_status` (только чтение): + `IN_PROCESS`, `WITH_ISSUES`.
- **Практика:** создавай в `PAUSED`, проверь, потом `ACTIVE`. `DELETED`/`ARCHIVED` — почти необратимо.

### `special_ad_categories`
`NONE`, `CREDIT`, `EMPLOYMENT`, `HOUSING`, `ISSUES_ELECTIONS_POLITICS`, `ONLINE_GAMBLING_AND_GAMING`, `FINANCIAL_PRODUCTS_SERVICES`. Регулируемые категории урезают таргетинг и триггерят более строгую модерацию.

### `buying_type`
`AUCTION` (дефолт, почти всё), `RESERVED`/`FIXED_CPM` (reach & frequency, ограничено). Задаётся при создании, **менять нельзя**.

### CBO (Advantage Campaign Budget)
Поставь `daily_budget` ИЛИ `lifetime_budget` + `bid_strategy` **на КАМПАНИИ**. Тогда у ад-сетов НЕ должно быть своего бюджета (Meta распределяет в реальном времени). Все ад-сеты — один тип бюджета и одна bid-стратегия. `lifetime_budget` требует `end_time`. Альтернатива — ABO (бюджет на каждом ад-сете).

### `bid_strategy` (Campaign и Ad Set)
- `LOWEST_COST_WITHOUT_CAP` (Highest Volume / авто — `bid_amount` не нужен)
- `LOWEST_COST_WITH_BID_CAP` (Bid Cap — **нужен** `bid_amount`)
- `COST_CAP` (Cost per Result — **нужен** `bid_amount`)
- `LOWEST_COST_WITH_MIN_ROAS` (ROAS — нужен `roas_average_floor`; только value-оптимизация)

---

## Создание ад-сета

`POST /act_<AD_ACCOUNT_ID>/adsets`

Ключевое: `name`, `campaign_id`, `optimization_goal`, `billing_event`, `targeting` (объект), `status`, `daily_budget`/`lifetime_budget` (ABO), `bid_amount`, `bid_strategy`, `start_time`/`end_time`, `promoted_object` (**нужен** для conversion/lead/app целей), `destination_type`, `adset_schedule` (дейпартинг), `frequency_control_specs`, `attribution_spec`, `is_dynamic_creative`. Всего ~90 полей.

### `optimization_goal`
`NONE`, `APP_INSTALLS`, `AD_RECALL_LIFT`, `ENGAGED_USERS`, `IMPRESSIONS`, `LEAD_GENERATION`, `QUALITY_LEAD`, `LINK_CLICKS`, `OFFSITE_CONVERSIONS`, `PAGE_LIKES`, `POST_ENGAGEMENT`, `QUALITY_CALL`, `REACH`, `LANDING_PAGE_VIEWS`, `VALUE`, `THRUPLAY`, `CONVERSATIONS`, `SUBSCRIBERS`, `MEANINGFUL_CALL_ATTEMPT`, … (должен быть совместим с objective).

**Совместимость (частые связки):**
- `OUTCOME_LEADS` → `LEAD_GENERATION` / `OFFSITE_CONVERSIONS` / `QUALITY_LEAD`
- `OUTCOME_TRAFFIC` → `LINK_CLICKS` / `LANDING_PAGE_VIEWS`
- `OUTCOME_SALES` → `OFFSITE_CONVERSIONS` / `VALUE`
- `OUTCOME_AWARENESS` → `REACH` / `IMPRESSIONS` / `AD_RECALL_LIFT`
- `OUTCOME_APP_PROMOTION` → `APP_INSTALLS` / `VALUE`

### `billing_event`
`IMPRESSIONS`, `CLICKS`, `LINK_CLICKS`, `APP_INSTALLS`, `PAGE_LIKES`, `POST_ENGAGEMENT`, `THRUPLAY`, `PURCHASE`, `NONE`. Для conversion/lead-сетов обычно `IMPRESSIONS`.

### `destination_type` (место конверсии)
`WEBSITE`, `APP`, `MESSENGER`, `WHATSAPP`, `INSTAGRAM_DIRECT`, `ON_AD` (мгновенная форма), `ON_POST`, `ON_PAGE`, `FACEBOOK`, `INSTAGRAM_PROFILE`, … Для Lead-формы: `ON_AD`. Для сайта: `WEBSITE`.

---

## Создание объявления

`POST /act_<AD_ACCOUNT_ID>/ads`

`name`, `adset_id`, `creative` (`{"creative_id":"<id>"}` или инлайн `object_story_spec`), `status`, `bid_amount`, `tracking_specs`, `conversion_domain` (нужен для многих web-conversion), `source_ad_id` (копирование).

`effective_status` объявления добавляет статусы ревью: `PENDING_REVIEW`, `DISAPPROVED`, `PREAPPROVED`, `PENDING_BILLING_INFO`, `ADSET_PAUSED`, `CAMPAIGN_PAUSED`, `WITH_ISSUES`, `IN_PROCESS`.

---

## Управление (edit / pause / activate / delete / copy)

- **Правка / пауза / запуск:** `POST /<OBJECT_ID>` (на ID объекта, НЕ на edge аккаунта) с полями. Пауза = `status=PAUSED`, запуск = `status=ACTIVE`. Успех: `{"success": true}`.
  ```bash
  curl -X POST -F 'status=PAUSED' -F 'access_token=<TOKEN>' https://graph.facebook.com/v25.0/<CAMPAIGN_ID>
  curl -X POST -F 'daily_budget=10000' -F 'access_token=<TOKEN>' https://graph.facebook.com/v25.0/<ADSET_ID>
  ```
  Пауза кампании каскадит `effective_status=CAMPAIGN_PAUSED` на детей, но НЕ меняет их собственный `status`.
- **Удаление:** `DELETE /<OBJECT_ID>` или `POST /<id> status=DELETED`. Удаление кампании удаляет её ад-сеты/объявления. Необратимо → предпочитай `PAUSED`/`ARCHIVED`.
- **Дублирование:** `POST /<OBJECT_ID>/copies`
  - Campaign: `deep_copy` (копировать детей), `status_option` (`ACTIVE`|`PAUSED`|`INHERITED_FROM_SOURCE`), `rename_options`, `parameter_overrides`.
  - Ad Set: `campaign_id` (цель), `deep_copy`, `create_dco_adset`, `status_option`.
  - Ad: `adset_id` (цель), `creative_parameters`, `rename_options`, `status_option`.

## Чтение / листинг

`GET /act_<id>/campaigns` | `/adsets` | `/ads` | `/adcreatives`. Спуск по дереву: `GET /<campaign_id>/adsets`, `/<adset_id>/ads`.
Поля: `?fields=id,name,status,effective_status,objective,daily_budget,bid_strategy`.
Фильтры: `&effective_status=['ACTIVE']`, `&filtering=[{...}]`.

---

## Таргетинг (`targeting` — один JSON на ад-сете)

Смешивает жёсткие ограничения (гео, возраст, пол, площадки) и «detailed targeting» (интересы/поведение/демография) + аудитории + исключения.

### Полный список полей `Targeting` (из SDK)
`age_min`, `age_max`, `age_range`, `genders`, `geo_locations`, `excluded_geo_locations`, `interests`, `behaviors`, `demographics`, `custom_audiences`, `excluded_custom_audiences`, `flexible_spec`, `exclusions`, `connections`, `excluded_connections`, `friends_of_connections`, `locales`, `education_statuses`, `education_majors`, `education_schools`, `college_years`, `work_positions`, `work_employers`, `industries`, `income`, `net_worth`, `home_ownership`, `home_type`, `home_value`, `family_statuses`, `relationship_statuses`, `life_events`, `interested_in`, `keywords`, `publisher_platforms`, `facebook_positions`, `instagram_positions`, `messenger_positions`, `audience_network_positions`, `threads_positions`, `whatsapp_positions`, `device_platforms`, `user_os`, `user_device`, `wireless_carrier`, `targeting_automation`, `targeting_optimization`, `targeting_relaxation_types`, `dynamic_audience_ids`, `product_audience_specs`, `radius`, `regions`, `cities`, `zips`, `countries`, `country_groups` … (полный список ~150 полей).

### `geo_locations` (TargetingGeoLocation)
Поля: `countries`, `regions`, `cities`, `zips`, `geo_markets`, `places`, `custom_locations`, `country_groups`, `location_types`, `metro_areas`, `neighborhoods`, `electoral_districts`, …
- `countries` = ISO-коды (`["US"]`).
- `regions`/`cities`/`zips`/`geo_markets`/`places` = массивы `{"key":"..."}` (opaque ID из поиска).
- `custom_locations` = `{latitude, longitude, radius, distance_unit}`.
- `location_types` = фильтр причины совпадения, напр. `['home','recent']`.

```json
"targeting": {
  "geo_locations": {
    "countries": ["FR"],
    "cities": [{"key": "2505639"}],
    "zips": [{"key": "US:98121"}]
  },
  "age_min": 25, "age_max": 45,
  "genders": [2],
  "flexible_spec": [
    { "interests": [{"id": 6003139266461, "name": "..."}] }
  ]
}
```

### Демография
- `age_min`/`age_max` — 13–65 (65 = 65+). `genders` — `[1]` муж, `[2]` жен, опустить = все. `locales` — ID из `type=adlocale`.
- `flexible_spec` — список объектов: элементы массива И-ятся, сегменты внутри объекта ИЛИ-ятся. `exclusions` — один объект сегментов для исключения.
- `interests`/`behaviors` = массивы `{"id":<num>,"name":"..."}` (id авторитетен).

### Поиск значений таргетинга
`GET /search?type=<TYPE>&q=<query>`:
`adinterest`, `adTargetingCategory` (+`class=interests|behaviors`), `adgeolocation`, `adzipcode`, `adcountry`, `adlocale`, `adworkposition`, `adworkemployer`, `adeducationschool`, `adeducationmajor`, `adinterestsuggestion`, `adinterestvalid`, `adradiussuggestion`, `adgeolocationmeta`.
Также edge-ы: `GET /act_{id}/targetingsearch`, `/targetingbrowse`, `/targetingsuggestions`.

### Оценка охвата
- `GET /act_{id}/reachestimate` → `{users, estimate_ready}`.
- `GET /{adset|act_id}/delivery_estimate` (берёт `optimization_goal` + `targeting_spec`) → `estimate_dau`, `estimate_mau_lower_bound`, `estimate_mau_upper_bound`, `estimate_ready`.

### Advantage+ Audience (важно)
Управляется `targeting_automation.advantage_audience = 1|0`. Включён по умолчанию для новых ад-сетов (с v23+). Когда включён: интересы/аудитории становятся **«подсказками»**, которые Meta может расширять; **жёсткими** остаются только location, минимальный возраст и исключения/excluded custom audiences. Чтобы жёстко контролировать таргетинг — `advantage_audience=0`.

---

## Загрузка креативов с локального компьютера (3 шага)

### Шаг 1a — Картинка
`POST /act_<AD_ACCOUNT_ID>/adimages` (multipart/form-data).
Имя part = имя файла (SDK: `files={filename: open(...)}`; curl: `-F '<name>=@/path/img.jpg'`).
Ответ **вложенный**: `{"images": {"<name>": {"hash": "<IMAGE_HASH>", "url": "..."}}}` → берёшь `images.<name>.hash`.
```bash
curl -X POST 'https://graph.facebook.com/v25.0/act_<ACT>/adimages' \
  -F 'pic=@/local/creative.jpg' -F 'access_token=<TOKEN>'
```
Лимит: JPG/PNG/GIF, ~30 МБ. Читать: `GET /act_<id>/adimages?fields=hash,url,width,height`. Удалить: `DELETE ...?hash=<HASH>`. Массово — .zip.

### Шаг 1b — Видео (чанковая resumable-загрузка)
`POST /act_<AD_ACCOUNT_ID>/advideos` в три фазы:
1. `upload_phase=start` + `file_size=<bytes>` → `upload_session_id`, `video_id`, `start_offset`, `end_offset`.
2. `upload_phase=transfer` (повторять): `upload_session_id`, `start_offset`, бинарный чанк `video_file_chunk` → новые оффсеты. Цикл пока `start_offset == end_offset`.
3. `upload_phase=finish` + `upload_session_id`, `title` → `success:true`.
Лимит: MP4/MOV/GIF (H.264/AAC), до 4 ГБ / 240 мин.

**Асинхронная обработка:** видео кодируется не сразу. Поллить `GET /{video_id}?fields=status` пока `video_status=ready` (`processing`/`error` — иначе). Есть `processing_progress` 0–100.

**Python SDK удобно:**
```python
video = AdVideo(parent_id=act_id)
video[AdVideo.Field.filepath] = '/local/video.mp4'
video.remote_create()
video.waitUntilEncodingReady()
vid = video['id']  # → в object_story_spec.video_data.video_id
```

> Есть ещё новый generic Resumable Upload API `/{APP_ID}/uploads` (возвращает file handle `h`), но для рекламных креативов стандарт — классические `adimages`/`advideos`.

### Шаг 2 — AdCreative (`object_story_spec`)
`object_story_spec` требует `page_id` (Page-backed «dark»-пост; токен-владелец = Admin/Editor Страницы) + **один из** `link_data` / `video_data` / `photo_data` / `template_data`. Опц. `instagram_user_id`.
`object_story_spec` и `object_story_id` — **взаимоисключающие**.

**`link_data`** (одиночная картинка/ссылка + контейнер карусели): `message`, `link` (обяз.), `image_hash`, `name` (заголовок), `description`, `caption`, `call_to_action`, `child_attachments` (карусель), `multi_share_optimized`, `format_option`. Используй `image_hash` (не `picture` URL) для локально загруженного.

**`video_data`**: `video_id` (обяз.), `image_hash` ИЛИ `image_url` (превью — одно обязательно), `message`, `title`, `link_description`, `call_to_action` (обычно нужен для видео).

**`photo_data`**: `image_hash`, `caption`.

**`call_to_action`**: `{type: <enum>, value: {link: "...", lead_gen_form_id: "..."}}`. Типы (130+): `LEARN_MORE`, `SHOP_NOW`, `SIGN_UP`, `SUBSCRIBE`, `BOOK_NOW`, `GET_STARTED`, `DOWNLOAD`, `INSTALL_APP`, `CONTACT_US`, `APPLY_NOW`, `ORDER_NOW`, `BUY_NOW`, `DONATE_NOW`, `MESSAGE_PAGE`, `WHATSAPP_MESSAGE`, `CALL_NOW`, `WATCH_VIDEO`, `NO_BUTTON`, **`LEAD`**, …

**Карусель:** `link_data.child_attachments` — 2–10 карточек, каждая: `link` (обяз.), `image_hash` ИЛИ `video_id`, `name`, `description`, `call_to_action`. Можно микс фото/видео.

### Шаг 3 — Создать creative и привязать
`POST /act_<AD_ACCOUNT_ID>/adcreatives` с `name` + `object_story_spec` → `creative_id`.
Привязать: `POST /act_<id>/ads` с `creative={"creative_id":"<ID>"}`.
> Если `object_story_spec`/`object_story_id` совпадает с существующим creative — API вернёт **существующий** id (дублей не создаёт).

**Продвинуть существующий пост Страницы:** НЕ строй `object_story_spec`, передай `object_story_id="<PAGE_ID>_<POST_ID>"`.

### Пример end-to-end (link-ad с локальной картинкой)
```bash
# 1) upload
curl -X POST 'https://graph.facebook.com/v25.0/act_<ACT>/adimages' \
  -F 'pic=@/local/creative.jpg' -F 'access_token=<TOKEN>'   # → images.pic.hash

# 2) creative
curl -X POST 'https://graph.facebook.com/v25.0/act_<ACT>/adcreatives' \
  -F 'name=Link Ad' \
  -F 'object_story_spec={"page_id":"<PAGE_ID>","link_data":{"message":"Body","link":"https://example.com","name":"Headline","image_hash":"<HASH>","call_to_action":{"type":"SIGN_UP","value":{"link":"https://example.com"}}}}' \
  -F 'access_token=<TOKEN>'   # → creative_id

# 3) ad
curl -X POST 'https://graph.facebook.com/v25.0/act_<ACT>/ads' \
  -F 'name=My Ad' -F 'adset_id=<ADSET_ID>' \
  -F 'creative={"creative_id":"<CREATIVE_ID>"}' \
  -F 'status=PAUSED' -F 'access_token=<TOKEN>'
```

---

## Инсайты / метрики (следить за результатами)

- Синхронно: `GET /act_<id>/insights?level=campaign|adset|ad` или `GET /<object_id>/insights`.
- **Асинхронно (для больших выгрузок):** `POST /act_<id>/insights` → `report_run_id` → поллинг `GET /<report_run_id>` (`async_status`, `async_percent_completion`) → `GET /<report_run_id>/insights`.
- Метрики: `spend`, `impressions`, `clicks`, `cpc`, `cpm`, `ctr`, `actions`, `cost_per_action_type`, `cost_per_result`.
- Разбивки: `age`, `gender`, `placement`, `publisher_platform`, `country` (есть лимиты на комбинации).
- Период: `date_preset` / `time_range` / `time_increment`.
- Атрибуция: `action_attribution_windows` (`1d_click`, `7d_click`, `1d_view`, `7d_view`) — влияет на число отчётных конверсий.

---

## Минимальный поток создания (пример «лиды»)

1. `POST /act_<id>/campaigns`: `objective=OUTCOME_LEADS`, `status=PAUSED`, `special_ad_categories=[]` → `campaign_id`.
2. `POST /act_<id>/adsets`: `campaign_id`, `optimization_goal=LEAD_GENERATION`, `billing_event=IMPRESSIONS`, `daily_budget=5000`, `targeting={...}`, `promoted_object={"page_id":"<PAGE_ID>"}`, `destination_type=ON_AD`, `status=PAUSED`, `start_time` → `adset_id`.
3. `POST /act_<id>/adcreatives`: `object_story_spec={page_id, link_data:{..., call_to_action:{type:LEAD, value:{lead_gen_form_id:<FORM_ID>}}}}` → `creative_id`.
4. `POST /act_<id>/ads`: `adset_id`, `creative={"creative_id":"<creative_id>"}`, `status=PAUSED` → `ad_id`.
5. Проверить → выставить `status=ACTIVE` на кампании/ад-сете/объявлении.

## Разрешения / рейт-лимиты (кратко; подробно — [04](04-access-auth-limits.md))
- Запись: `ads_management`. Чтение: `ads_read`.
- Рейт-лимит `ads_management` (BUC, скользящий час на ad account): Dev/Limited = `300 + 40×активных объявлений`; Standard/Full = `100000 + 40×...`. Decay 300 сек. Мониторь `X-Business-Use-Case-Usage`. Ошибка throttle: `80004` / subcode `2446079`.
