"""Read generated clips back from data/clips/<slug>/."""

from __future__ import annotations

import json
from pathlib import Path

from clipper import config


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _video_dir(slug: str) -> Path | None:
    d = (config.CLIPS_DIR / slug).resolve()
    return d if d.parent == config.CLIPS_DIR.resolve() and d.is_dir() else None


def _can_reclip(slug: str, src: dict) -> bool:
    """New clips can be made if the transcript is saved and the source can be fetched again."""
    has_transcript = (config.WORK_DIR / slug / "transcript.json").exists()
    source = src.get("source") or src.get("url")
    return has_transcript and bool(src.get("url") or (source and Path(source).exists()))


def list_videos() -> list[dict]:
    """One entry per processed source video, newest first."""
    if not config.CLIPS_DIR.exists():
        return []
    items = []
    for d in config.CLIPS_DIR.iterdir():
        jsons = sorted(d.glob("*.json")) if d.is_dir() else []
        if not jsons:
            continue
        src = _read_json(jsons[0]).get("source_video") or {}
        items.append({
            "slug": d.name,
            "title": src.get("title") or d.name,
            "channel": src.get("channel"),
            "url": src.get("url"),
            "clip_count": len(jsons),
            "updated": max(p.stat().st_mtime for p in jsons),
            "thumbnail": f"https://i.ytimg.com/vi/{src['id']}/mqdefault.jpg"
                         if src.get("url") and src.get("id") else None,
        })
    items.sort(key=lambda x: -x["updated"])
    return items


def get_clips(slug: str, media_prefix: str = "/media") -> dict | None:
    """All clips for one source video. File URLs are {media_prefix}/clips/<slug>/<file>."""
    d = _video_dir(slug)
    if d is None:
        return None
    clips = []
    for path in sorted(d.glob("*.json")):
        c = _read_json(path)
        if not c:
            continue
        video = d / (c.get("video_file") or f"{path.stem}.mp4")
        c["name"] = c.get("name") or path.stem
        c["video"] = f"{media_prefix}/clips/{slug}/{video.name}" if video.exists() else None
        c["json"] = f"{media_prefix}/clips/{slug}/{path.name}"
        clips.append(c)
    if not clips:
        return None
    src = clips[0].get("source_video") or {}
    return {
        "slug": slug,
        "title": src.get("title") or slug,
        "source_video": src,
        "can_reclip": _can_reclip(slug, src),
        "clips": clips,
    }
