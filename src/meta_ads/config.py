import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = parent of src/. Resolving `.env` absolutely (not relative to
# CWD) lets the worker, CLI, and MCP server all find it no matter where they
# are launched from — the MCP server in particular is spawned by Claude Code
# with an unpredictable working directory. (Mirrors google-ads.)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Meta app + assets ───────────────────────────────────────────
    meta_app_id: str = Field(default="")
    meta_app_secret: SecretStr = Field(default=SecretStr(""))
    meta_api_version: str = Field(default="v25.0")
    meta_ad_account_id: str = Field(default="")  # act_<id>
    meta_page_id: str = Field(default="")
    # Additional Facebook Pages the workspace advertises from (multi-project:
    # e.g. the Sunraf Page next to the Melia one). Comma/semicolon-separated
    # ids; empty = single-page behaviour, byte-identical to before this knob
    # existed. Each extra Page needs the System User to hold a role on it
    # (Page tokens are minted per page) and the app subscribed to its leadgen
    # webhook. The webhook relay records page_id per lead; the resolver uses
    # it to pick the right Page token, and the reconciler sweeps every listed
    # Page's forms.
    meta_extra_page_ids: str = Field(default="")
    meta_dataset_id: str = Field(default="")  # Conversions API dataset

    # Bootstrap tokens (primary copies live encrypted in meta.oauth_tokens).
    meta_system_user_token: SecretStr = Field(default=SecretStr(""))
    meta_page_token: SecretStr = Field(default=SecretStr(""))

    # ─── Service secrets ─────────────────────────────────────────────
    fb_token_encryption_key: SecretStr = Field(default=SecretStr(""))
    fb_ingest_hmac_secret: SecretStr = Field(default=SecretStr(""))

    # ─── Database + CRM handoff ──────────────────────────────────────
    fb_database_url: str = Field(default="postgresql+psycopg://localhost/meta_dev")
    crm_ingest_url: str = Field(default="https://crm.kvadra.me/api/ads/meta/lead-ingest")

    # ─── Mutation safety ─────────────────────────────────────────────
    fb_allow_mutations: bool = False
    fb_dry_run_default: bool = True

    # ─── Local creatives (pipeline A reads from disk) ────────────────
    creative_source_dirs: str = Field(default="")  # ';'-separated paths

    # ─── IG auto-boost (worker job ig_boost) ─────────────────────────
    fb_ig_boost_enabled: bool = False
    fb_ig_user_id: str = Field(default="")  # IG professional-account user id
    # Caption lint gate. Default OFF — user decision 2026-07-10 (D-11):
    # boost EVERYTHING published, no filters of ours.
    fb_ig_boost_lint_enabled: bool = False

    # ─── Lead reconciliation (worker job lead_poll) ──────────────────
    # Safety net for leadgen webhooks that never arrive. Meta keeps leads
    # retrievable for 90 days, so a miss is recoverable — but only if something
    # actually looks.
    fb_lead_poll_enabled: bool = True
    # Routine window per form. Wide enough to cover a webhook Meta retried and
    # gave up on, narrow enough that each poll returns almost nothing.
    fb_lead_poll_lookback_hours: int = 24
    # When Meta's leads_count exceeds ours, scan the newest pages with no time
    # filter instead — leads come back newest-first, so a small gap surfaces at
    # once however old it is.
    fb_lead_poll_deep_pages: int = 2
    fb_lead_poll_max_pages: int = 5
    # Recorded failures are re-tried until this many attempts, then left alone
    # for a human (they stay visible as crm_lead_id IS NULL).
    fb_lead_poll_max_attempts: int = 5
    fb_lead_poll_retry_limit: int = 25

    # ─── Telegram ────────────────────────────────────────────────────
    telegram_bot_token: SecretStr = Field(default=SecretStr(""))
    telegram_fb_chat_id: str = Field(default="")

    # ─── App ─────────────────────────────────────────────────────────
    fb_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    fb_timezone: str = "Europe/Podgorica"

    @property
    def graph_base(self) -> str:
        return f"https://graph.facebook.com/{self.meta_api_version}"

    @property
    def meta_configured(self) -> bool:
        return bool(
            self.meta_app_id
            and self.meta_app_secret.get_secret_value()
            and self.meta_ad_account_id
            and self.meta_page_id
        )

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token.get_secret_value() and self.telegram_fb_chat_id)

    @property
    def creative_dirs(self) -> list[Path]:
        return [Path(p.strip()) for p in self.creative_source_dirs.split(";") if p.strip()]

    @property
    def page_ids(self) -> list[str]:
        """Every Page the service works with: the primary + META_EXTRA_PAGE_IDS.

        Ordered (primary first), deduplicated. With no extras this is exactly
        [meta_page_id], so single-page installs behave as before."""
        out: list[str] = []
        for pid in [self.meta_page_id, *re.split(r"[;,]", self.meta_extra_page_ids)]:
            pid = pid.strip()
            if pid and pid not in out:
                out.append(pid)
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
