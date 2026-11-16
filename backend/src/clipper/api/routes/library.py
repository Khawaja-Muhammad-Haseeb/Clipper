from fastapi import APIRouter, HTTPException

from clipper import library

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
