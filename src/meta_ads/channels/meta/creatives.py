"""Pipeline A — upload photo/video creatives FROM LOCAL DISK to Meta.

No cloud intermediary: reads the file from the user's machine (melia-montage
renders) and uploads via adimages/advideos. Uploads are cached in
`meta.creative_upload` (path + mtime + size) so the same file is never sent twice.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from meta_ads.channels.meta.client import SYSTEM_USER, GraphClient
from meta_ads.config import get_settings

logger = logging.getLogger(__name__)

_CHUNK = 25 * 1024 * 1024  # 25 MB transfer chunks for resumable video upload


async def upload_image(path: str | Path) -> str:
    """POST /act_<id>/adimages (multipart). Returns image_hash. TODO: wire cache."""
    raise NotImplementedError(
        "TODO(phase1): multipart POST to /act_<id>/adimages, return images.<name>.hash; "
        "check meta.creative_upload first."
    )


async def upload_video(path: str | Path) -> str:
    """Chunked resumable upload to /act_<id>/advideos (start→transfer→finish),
    then poll GET /{video_id}?fields=status until 'ready'. Returns video_id.

    TODO(phase1): implement the three phases + encoding poll + cache."""
    raise NotImplementedError("TODO(phase1): advideos chunked upload + encoding poll")


def build_object_story_spec(
    *,
    page_id: str,
    lead_gen_form_id: str,
    message: str,
    image_hash: str | None = None,
    video_id: str | None = None,
    instagram_user_id: str | None = None,
) -> dict[str, Any]:
    """AdCreative object_story_spec with CTA type=LEAD → the lead form.

    Note: IG placements need instagram_user_id or the ad silently won't run on IG."""
    cta = {"type": "LEAD", "value": {"lead_gen_form_id": lead_gen_form_id}}
    spec: dict[str, Any] = {"page_id": page_id}
    if video_id:
        spec["video_data"] = {"video_id": video_id, "call_to_action": cta, "message": message}
    elif image_hash:
        spec["link_data"] = {"image_hash": image_hash, "call_to_action": cta, "message": message}
    else:
        raise ValueError("need image_hash or video_id")
    if instagram_user_id:
        spec["instagram_user_id"] = instagram_user_id
    return spec


async def create_creative(name: str, object_story_spec: dict[str, Any]) -> str:
    """POST /act_<id>/adcreatives → creative_id. TODO(phase1)."""
    settings = get_settings()
    async with await GraphClient.for_provider(SYSTEM_USER) as g:
        _ = g, settings, name, object_story_spec  # placeholder
    raise NotImplementedError("TODO(phase1): create adcreative")
