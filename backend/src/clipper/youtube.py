"""YouTube access with yt-dlp (no API key): channel search, video lists, downloads."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote_plus

import yt_dlp

from clipper import config
from clipper.media import FFMPEG
from clipper.reporting import log, progress
from clipper.utils import slugify

_BASE = {"quiet": True, "no_warnings": True, "noprogress": True}
_CHANNEL_FILTER = "EgIQAg%253D%253D"  # YouTube search filter: type = channel


# ---- Channels & videos ------------------------------------------------------
def find_channels(name: str, limit: int = 5) -> list[dict]:
    """Search YouTube for channels matching `name`."""
    url = f"https://www.youtube.com/results?search_query={quote_plus(name)}&sp={_CHANNEL_FILTER}"
    with yt_dlp.YoutubeDL({**_BASE, "extract_flat": "in_playlist", "playlistend": limit}) as ydl:
        info = ydl.extract_info(url, download=False)
    out = []
    for e in (info.get("entries") or [])[:limit]:
        if not e.get("channel_id"):
            continue
        out.append({
            "name": e.get("channel") or e.get("title"),
            "handle": e.get("uploader_id"),
            "id": e["channel_id"],
            "url": f"https://www.youtube.com/channel/{e['channel_id']}",
            "subscribers": e.get("channel_follower_count"),
        })
    return out


def channel_from_input(text: str) -> dict | None:
    """Resolve an exact @handle or channel URL directly. Returns None if it isn't one."""
    text = text.strip()
    if text.startswith("@"):
        url = f"https://www.youtube.com/{text}"
    elif re.match(r"https?://(www\.)?youtube\.com/(@|channel/|c/|user/)", text):
        url = text.split("?")[0].rstrip("/")
        url = re.sub(r"/(videos|shorts|streams|featured|about)$", "", url)
    else:
        return None
    with yt_dlp.YoutubeDL({**_BASE, "extract_flat": "in_playlist", "playlistend": 1}) as ydl:
        info = ydl.extract_info(f"{url}/videos", download=False)
    return {
        "name": info.get("channel") or info.get("uploader"),
        "handle": info.get("uploader_id"),
        "id": info.get("channel_id"),
        "url": f"https://www.youtube.com/channel/{info.get('channel_id')}",
        "subscribers": info.get("channel_follower_count"),
    }


def _video_details(video_id: str, fallback: dict) -> dict:
    try:
        with yt_dlp.YoutubeDL({**_BASE, "skip_download": True}) as ydl:
            i = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    except Exception:  # noqa: BLE001 - members-only / removed videos etc.
        i = fallback
    return {
        "id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": i.get("title") or fallback.get("title"),
        "description": (i.get("description") or "").strip(),
        "upload_date": i.get("upload_date"),
        "duration": i.get("duration") or fallback.get("duration"),
        "live_status": i.get("live_status"),
        "view_count": i.get("view_count") or fallback.get("view_count"),
        "thumbnail": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
    }


def latest_videos(channel: dict, start: int, count: int) -> list[dict]:
    """Videos `start`..`start+count-1` (1-based, newest first) from the channel's Videos tab.
    Shorts and livestreams live on other tabs, so they're excluded automatically."""
    opts = {**_BASE, "extract_flat": "in_playlist",
            "playliststart": start, "playlistend": start + count - 1}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"{channel['url']}/videos", download=False)
    flat = [e for e in (info.get("entries") or []) if e.get("id")]
    if not flat:
        return []
    with ThreadPoolExecutor(max_workers=len(flat)) as pool:
        videos = list(pool.map(lambda e: _video_details(e["id"], e), flat))
    return [v for v in videos if v["live_status"] not in ("is_upcoming", "is_live")]


# ---- Download ---------------------------------------------------------------
def download(url: str) -> tuple[Path, dict]:
    config.DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    finished: set[str] = set()

    def hook(d):
        # Video and audio arrive as two files; report the average of both.
        if d["status"] == "finished":
            finished.add(d.get("filename", ""))
            progress("download", min(1.0, len(finished) / 2))
        elif d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            frac = (d.get("downloaded_bytes", 0) / total) if total else 0
            speed = (d.get("_speed_str") or "").strip()
            progress("download", min(0.99, (len(finished) + frac) / 2), speed or None)

    opts = {
        **_BASE,
        "progress_hooks": [hook],
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(config.DOWNLOADS_DIR / "%(id)s.%(ext)s"),
        "ffmpeg_location": FFMPEG,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        path = config.DOWNLOADS_DIR / f"{info['id']}.mp4"
        if path.exists():
            log(f"Already downloaded: {path.name}")
        else:
            log(f"Downloading: {info.get('title')}")
            ydl.download([url])
    return path, {
        "id": info.get("id"),
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "url": info.get("webpage_url") or url,
        "description": (info.get("description") or "")[:1500],
    }


def get_video(source: str) -> tuple[Path, dict]:
    """A local file path, or anything yt-dlp can download."""
    local = Path(source)
    if local.exists():
        return local.resolve(), {"id": slugify(local.stem), "title": local.stem,
                                 "channel": None, "url": None, "description": ""}
    return download(source)
