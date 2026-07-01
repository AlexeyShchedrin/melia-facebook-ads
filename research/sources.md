# Источники

Собрано 2026-07-01. Приоритет — официальные `developers.facebook.com` / `developers.meta.com` и реальные репозитории. Часть страниц Meta рендерится клиентски и обрезалась фетчером — тогда факты сверены с официальным `facebook-python-business-sdk` (кодогенерится из спеки API 1:1).

## Официальные доки Meta — версии и общее
- Changelog версий: https://developers.facebook.com/docs/graph-api/changelog/versions/
- Анонс v25.0: https://developers.facebook.com/blog/post/2026/02/18/introducing-graph-api-v25-and-marketing-api-v25/
- Обзор Marketing API: https://developers.facebook.com/docs/marketing-api/overview

## Объектная модель / кампании / креативы
- Reference ad-campaign (ад-сет): https://developers.facebook.com/docs/marketing-api/reference/ad-campaign/
- Manage campaigns: https://developers.facebook.com/docs/marketing-api/get-started/manage-campaigns/
- Basic ad creation: https://developers.facebook.com/docs/marketing-api/get-started/basic-ad-creation/create-an-ad-campaign/
- Advantage Campaign Budget: https://developers.facebook.com/docs/marketing-api/bidding/guides/advantage-campaign-budget/
- Ad-set optimization: https://developers.facebook.com/docs/marketing-api/bidding/guides/ad-set-optimization
- adimages: https://developers.facebook.com/docs/marketing-api/reference/ad-account/adimages/
- object_story_spec: https://developers.facebook.com/docs/marketing-api/reference/ad-creative-object-story-spec/
- link_data: https://developers.facebook.com/docs/marketing-api/reference/ad-creative-link-data/
- video_data: https://developers.facebook.com/docs/marketing-api/reference/ad-creative-video-data/
- child_attachment (карусель): https://developers.facebook.com/docs/marketing-api/reference/ad-creative-link-data-child-attachment/
- asset_feed_spec: https://developers.facebook.com/docs/marketing-api/reference/ad-creative-asset-feed-spec/
- video-status: https://developers.facebook.com/docs/graph-api/reference/video-status/
- Resumable Upload API: https://developers.facebook.com/docs/graph-api/guides/upload/
- Insights: https://developers.facebook.com/docs/marketing-api/insights/
- adcreatives edge: https://developers.facebook.com/docs/marketing-api/reference/ad-account/adcreatives/

## Таргетинг
- Basic targeting: https://developers.facebook.com/docs/marketing-api/audiences/reference/basic-targeting/
- Detailed targeting: https://developers.facebook.com/docs/marketing-api/audiences/reference/detailed-targeting/

## Lead Ads
- Reference leadgen_forms: https://developers.facebook.com/docs/graph-api/reference/page/leadgen_forms/
- Webhooks for leadgen: https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-leadgen/
- Webhooks getting started (подпись/handshake): https://developers.facebook.com/docs/graph-api/webhooks/getting-started/
- Retrieving leads: https://developers.facebook.com/documentation/ads-commerce/marketing-api/guides/lead-ads/retrieving
- Webhooks integration quickstart: https://developers.facebook.com/documentation/ads-commerce/marketing-api/guides/lead-ads/quickstart/webhooks-integration
- lead-gen-data/leads: https://developers.facebook.com/docs/graph-api/reference/lead-gen-data/leads/
- Lead Ads Testing Tool: https://developers.facebook.com/tools/lead-ads-testing/
- Conversion Leads (CAPI for CRM): https://developers.facebook.com/docs/marketing-api/conversions-api/conversion-leads-integration/
- Об истёкших лидах (90 дней): https://www.facebook.com/business/help/1526849577619206

## Доступы / токены / рейт-лимиты
- Authorization: https://developers.facebook.com/docs/marketing-api/get-started/authorization
- Marketing API use cases (создание app): https://developers.facebook.com/docs/development/create-an-app/marketing-api-use-cases/
- Обновление access-тира (переименование, 500-порог): https://developers.meta.com/blog/updates-to-ads-management-standard-access-feature/
- Permissions reference: https://developers.facebook.com/docs/permissions/
- App modes (dev/live): https://developers.facebook.com/docs/development/build-and-test/app-modes/
- System Users overview: https://developers.facebook.com/docs/business-management-apis/system-users/overview/
- System Users — генерация токенов: https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens/
- Access tokens: https://developers.facebook.com/docs/facebook-login/guides/access-tokens
- Токены — отладка/ошибки: https://developers.facebook.com/docs/facebook-login/guides/access-tokens/debugging-and-error-handling
- Rate limiting (Graph): https://developers.facebook.com/docs/graph-api/overview/rate-limiting/
- Rate limiting (Marketing): https://developers.facebook.com/docs/marketing-api/overview/rate-limiting/
- Error handling: https://developers.facebook.com/docs/graph-api/guides/error-handling/
- Data Deletion callback: https://developers.facebook.com/docs/development/create-an-app/data-deletion-callback/
- App Review: https://developers.facebook.com/docs/app-review/
- Business Manager API: https://developers.facebook.com/docs/marketing-api/business-manager-api

## SDK и примеры
- facebook-python-business-sdk: https://github.com/facebook/facebook-python-business-sdk
  - adaccount.py, campaign.py, adset.py, adcreative.py, targeting.py, page.py, leadgenform.py, adimage.py, video_uploader.py
- fbsamples/marketing-api-samples: https://github.com/fbsamples/marketing-api-samples
  - samples/samplecode/lead_ad.py, adcreation.py
- Пример upload_video: https://github.com/facebook/facebook-python-business-sdk/blob/main/examples/upload_video.py

## MCP-серверы
- Официальный Meta Ads AI Connectors: https://mcp.facebook.com/ads · анонс https://www.facebook.com/business/news/meta-ads-ai-connectors · help https://www.facebook.com/business/help/1456422242197840
- pipeboard-co/meta-ads-mcp: https://github.com/pipeboard-co/meta-ads-mcp · https://pypi.org/project/meta-ads-mcp/ · https://pipeboard.co
- gomarble-ai/facebook-ads-mcp-server: https://github.com/gomarble-ai/facebook-ads-mcp-server
- mikusnuz/meta-ads-mcp: https://github.com/mikusnuz/meta-ads-mcp
- serkanhaslak/meta-mcp: https://github.com/serkanhaslak/meta-mcp
- hashcott/meta-ads-mcp-server: https://github.com/hashcott/meta-ads-mcp-server
- byadsco/meta-ads-mcp: https://github.com/byadsco/meta-ads-mcp
- brijr/meta-mcp: https://github.com/brijr/meta-mcp
- Mike25app/scaleforge-mcp-meta-ads: https://github.com/Mike25app/scaleforge-mcp-meta-ads · npm @getscaleforge/mcp-meta-ads
- oliverames/meta-mcp-server (архив): https://github.com/oliverames/meta-mcp-server
- RamsesAguirre777/facebook-ads-library-mcp (Ad Library, не управление): https://github.com/RamsesAguirre777/facebook-ads-library-mcp
- Zapier Facebook Lead Ads MCP: https://zapier.com/mcp/facebook-lead-ads
- Coupler.io Facebook Ads MCP: https://www.coupler.io/mcp/facebook-ads

## Альтернативы (build-vs-buy)
- n8n Facebook Lead Ads trigger: https://docs.n8n.io/integrations/builtin/trigger-nodes/n8n-nodes-base.facebookleadadstrigger/

## Замечания по достоверности
- Часть reference-страниц Meta (authorization, rate-limiting, retrieving-leads, targeting) отдавалась фетчеру обрезанной → факты по эндпоинтам/enum/полям сверены с `facebook-python-business-sdk` (референс-клиент) и подтверждающими источниками.
- Формулы/лимиты (30 МБ картинка, 4 ГБ видео, `200×24×leads-90d`, 100 QPS) — в основном из спецификаций/вторичных сводок; сверять по live-докам и `X-Business-Use-Case-Usage` в рантайме.
- Точная минимальная связка разрешений для лидов имеет расхождение в двух офиц. страницах Meta (`pages_manage_metadata` vs `pages_manage_ads`) — запрашивать оба.
