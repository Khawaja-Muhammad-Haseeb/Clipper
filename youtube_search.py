"""YouTube lookups with yt-dlp (no API key needed)."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

import yt_dlp

_BASE = {"quiet": True, "no_warnings": True, "noprogress": True}
CHANNEL_FILTER = "EgIQAg%253D%253D"  # YouTube search filter: type = channel


def find_channels(name: str, limit: int = 5) -> list[dict]:
    """Search YouTube for channels matching `name`."""
    url = f"https://www.youtube.com/results?search_query={quote_plus(name)}&sp={CHANNEL_FILTER}"
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


def _details(video_id: str, fallback: dict) -> dict:
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
    with ThreadPoolExecutor(max_workers=max(1, len(flat))) as pool:
        videos = list(pool.map(lambda e: _details(e["id"], e), flat))
    return [v for v in videos if v["live_status"] not in ("is_upcoming", "is_live")]
