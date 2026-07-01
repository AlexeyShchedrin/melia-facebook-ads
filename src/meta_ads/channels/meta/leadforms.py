"""Instant (lead) forms — create & read via the Page.

Quality knobs that reduce junk (see research/05): is_optimized_for_quality,
is_phone_sms_verify_enabled, custom questions. `privacy_policy` is mandatory.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def create_leadgen_form(
    *,
    name: str,
    questions: list[dict[str, Any]],
    privacy_policy: dict[str, str],
    is_optimized_for_quality: bool = True,
    is_phone_sms_verify_enabled: bool = False,
    context_card: dict[str, Any] | None = None,
    thank_you_page: dict[str, Any] | None = None,
) -> str:
    """POST /{page_id}/leadgen_forms (Page token). Returns form_id. TODO(phase1)."""
    raise NotImplementedError("TODO(phase1): create leadgen form via Page token")


async def list_forms(page_id: str) -> list[dict[str, Any]]:
    """GET forms on the Page (for the polling reconciler to enumerate). TODO(phase1)."""
    raise NotImplementedError("TODO(phase1): list leadgen forms")
