"""`fb creative upload <path>` — upload a local photo/video to Meta."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from meta_ads.channels.meta import creatives

app = typer.Typer(no_args_is_help=True)

_VIDEO_EXT = {".mp4", ".mov", ".gif"}


@app.command("upload")
def upload(path: str) -> None:
    """Upload a creative from LOCAL DISK; prints the image_hash / video_id."""
    p = Path(path)
    if not p.is_file():
        raise typer.BadParameter(f"not a file: {p}")

    async def _run() -> str:
        if p.suffix.lower() in _VIDEO_EXT:
            return await creatives.upload_video(p)
        return await creatives.upload_image(p)

    try:
        ref = asyncio.run(_run())
        typer.echo(ref)
    except NotImplementedError as exc:
        typer.echo(f"[skeleton] {exc}")
