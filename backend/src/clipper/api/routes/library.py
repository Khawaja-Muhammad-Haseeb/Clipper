import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from clipper import library
from clipper.errors import ClipperError

router = APIRouter(prefix="/library", tags=["library"])


@router.get("")
def list_library():
    return {"items": library.list_videos()}


@router.get("/{slug}")
def library_item(slug: str):
    item = library.get_clips(slug, media_prefix="/media")
    if item is None:
        raise HTTPException(404, "No clips found")
    return item


@router.get("/{slug}/{name}/download")
def download(slug: str, name: str, platform: Literal["instagram", "youtube", "none"] = "none"):
    """The clip with that platform's end screen joined on (or the bare clip for 'none')."""
    tmp = Path(tempfile.mkdtemp())
    dst = tmp / f"{name}{'' if platform == 'none' else '_' + platform}.mp4"
    try:
        library.export(slug, name, None if platform == "none" else platform, dst)
    except ClipperError as e:
        raise HTTPException(404, str(e)) from e

    def cleanup() -> None:
        dst.unlink(missing_ok=True)
        tmp.rmdir()

    return FileResponse(dst, media_type="video/mp4", filename=dst.name, background=BackgroundTask(cleanup))
