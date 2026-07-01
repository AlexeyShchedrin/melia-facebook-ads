"""Pipeline A — upload photo/video creatives FROM LOCAL DISK to Meta.

No cloud intermediary: reads the file from the user's machine (melia-montage
renders) and uploads via adimages/advideos. Uploads are cached in
`meta.creative_upload` (path + mtime + size) so the same file is never sent twice.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text

from meta_ads.channels.meta.client import SYSTEM_USER, GraphClient
from meta_ads.config import get_settings

logger = logging.getLogger(__name__)

_CHUNK = 25 * 1024 * 1024  # transfer chunk ceiling; Meta returns the real offsets
VIDEO_EXT = {".mp4", ".mov", ".gif"}


def _stat(path: Path) -> tuple[int, int]:
    st = path.stat()
    return st.st_mtime_ns, st.st_size


def _read_slice(path: Path, offset: int, length: int) -> bytes:
    """Blocking file read — call via asyncio.to_thread so the event loop stays free."""
    with open(path, "rb") as fh:
        fh.seek(offset)
        return fh.read(length)


async def _cache_get(path: Path, kind: str) -> str | None:
    mtime, size = _stat(path)
    try:
        from meta_ads.db import async_session_maker  # noqa: PLC0415

        async with async_session_maker() as s:
            row = (
                await s.execute(
                    text(
                        "SELECT image_hash, video_id FROM meta.creative_upload "
                        "WHERE local_path=:p AND mtime_ns=:m AND size_bytes=:s AND status='ready'"
                    ),
                    {"p": str(path), "m": mtime, "s": size},
                )
            ).first()
    except Exception:
        logger.debug("creative_upload cache unavailable (get) — skipping", exc_info=True)
        return None
    if row is None:
        return None
    return row.image_hash if kind == "image" else row.video_id


async def _cache_put(path: Path, kind: str, *, image_hash: str | None = None, video_id: str | None = None) -> None:
    mtime, size = _stat(path)
    try:
        from meta_ads.db import async_session_maker  # noqa: PLC0415

        async with async_session_maker() as s:
            await s.execute(
                text(
                    "INSERT INTO meta.creative_upload "
                    "(local_path, mtime_ns, size_bytes, kind, image_hash, video_id, status) "
                    "VALUES (:p,:m,:s,:k,:ih,:vid,'ready') "
                    "ON CONFLICT (local_path, mtime_ns, size_bytes) DO UPDATE SET "
                    "image_hash=EXCLUDED.image_hash, video_id=EXCLUDED.video_id, status='ready'"
                ),
                {"p": str(path), "m": mtime, "s": size, "k": kind, "ih": image_hash, "vid": video_id},
            )
            await s.commit()
    except Exception:
        logger.debug("creative_upload cache unavailable (put) — skipping", exc_info=True)


async def upload_image(path: str | Path) -> str:
    """POST /act_<id>/adimages (multipart). Returns image_hash (cached)."""
    path = Path(path)
    if (cached := await _cache_get(path, "image")) is not None:
        logger.info("image cache hit: %s -> %s", path.name, cached)
        return cached
    act = get_settings().meta_ad_account_id
    if not act:
        raise RuntimeError("META_AD_ACCOUNT_ID not set")
    data = await asyncio.to_thread(path.read_bytes)
    async with await GraphClient.for_provider(SYSTEM_USER) as g:
        resp = await g.post(
            f"{act}/adimages",
            files={"source": (path.name, data, "application/octet-stream")},
        )
    images = resp.get("images") or {}
    if not images:
        raise RuntimeError(f"adimages returned no images: {resp}")
    image_hash = next(iter(images.values()))["hash"]
    await _cache_put(path, "image", image_hash=image_hash)
    logger.info("uploaded image %s -> %s", path.name, image_hash)
    return image_hash


async def upload_video(path: str | Path) -> str:
    """Chunked resumable upload to /act_<id>/advideos, then poll until 'ready'.
    Returns video_id (cached)."""
    path = Path(path)
    if (cached := await _cache_get(path, "video")) is not None:
        logger.info("video cache hit: %s -> %s", path.name, cached)
        return cached
    act = get_settings().meta_ad_account_id
    if not act:
        raise RuntimeError("META_AD_ACCOUNT_ID not set")
    size = path.stat().st_size

    async with await GraphClient.for_provider(SYSTEM_USER) as g:
        start = await g.post(f"{act}/advideos", data={"upload_phase": "start", "file_size": str(size)})
        session_id = start["upload_session_id"]
        video_id = start["video_id"]
        start_off, end_off = int(start["start_offset"]), int(start["end_offset"])

        while start_off < end_off:
            chunk = await asyncio.to_thread(
                _read_slice, path, start_off, min(end_off - start_off, _CHUNK)
            )
            r = await g.post(
                f"{act}/advideos",
                data={"upload_phase": "transfer", "upload_session_id": session_id, "start_offset": str(start_off)},
                files={"video_file_chunk": ("chunk", chunk, "application/octet-stream")},
            )
            start_off, end_off = int(r["start_offset"]), int(r["end_offset"])

        await g.post(
            f"{act}/advideos",
            data={"upload_phase": "finish", "upload_session_id": session_id, "title": path.stem},
        )
        await _wait_ready(g, video_id)

    await _cache_put(path, "video", video_id=video_id)
    logger.info("uploaded video %s -> %s", path.name, video_id)
    return video_id


async def _wait_ready(g: GraphClient, video_id: str, *, timeout_s: int = 900, interval_s: int = 5) -> None:
    waited = 0
    while waited < timeout_s:
        st = await g.get(video_id, params={"fields": "status"})
        status = (st.get("status") or {}).get("video_status")
        if status == "ready":
            return
        if status == "error":
            raise RuntimeError(f"video {video_id} processing error: {st}")
        await asyncio.sleep(interval_s)
        waited += interval_s
    raise TimeoutError(f"video {video_id} not 'ready' after {timeout_s}s")


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

    IG placements need instagram_user_id or the ad silently won't run on IG."""
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
    """POST /act_<id>/adcreatives → creative_id."""
    act = get_settings().meta_ad_account_id
    async with await GraphClient.for_provider(SYSTEM_USER) as g:
        resp = await g.post(
            f"{act}/adcreatives",
            data={"name": name, "object_story_spec": json.dumps(object_story_spec)},
        )
    return resp["id"]
