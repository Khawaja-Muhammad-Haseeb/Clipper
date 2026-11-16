"""YouTuber search, topic check and file upload."""

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from clipper import analysis, config, llm, youtube
from clipper.api.schemas import ChannelQuery, VideoQuery
from clipper.errors import ClipperError

router = APIRouter(tags=["search"])

# (channel_id, start, count) -> videos. Lets a topic change re-check without refetching.
_video_cache: dict[tuple, list[dict]] = {}


@router.post("/channels")
def channels(q: ChannelQuery):
    text = q.query.strip()
    if not text:
        raise HTTPException(400, "Enter a YouTuber name or @handle")
    try:
        direct = youtube.channel_from_input(text)
        return {"channels": [direct] if direct else youtube.find_channels(text)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"YouTube lookup failed: {e}") from e


@router.post("/videos")
def videos(q: VideoQuery):
    topic = q.topic.strip()
    if not topic:
        raise HTTPException(400, "Enter a topic")
    key = (q.channel.get("id"), q.start, q.count)
    try:
        if key not in _video_cache:
            _video_cache[key] = youtube.latest_videos(q.channel, q.start, q.count)
        vids = _video_cache[key]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not load videos: {e}") from e

    page = {"start": q.start, "count": q.count}
    if not vids:
        return {**page, "videos": [], "end_of_channel": True}
    try:
        matches = {v["id"]: reason for v, reason in analysis.check_topic(llm.client(), vids, topic)}
    except ClipperError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Topic check failed: {e}") from e
    return {
        **page,
        "videos": [{**v, "matched": v["id"] in matches, "reason": matches.get(v["id"], "")} for v in vids],
        "end_of_channel": False,
    }


@router.post("/upload")
def upload(file: UploadFile):
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.UPLOADS_DIR / Path(file.filename or "video.mp4").name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"path": str(dest)}
