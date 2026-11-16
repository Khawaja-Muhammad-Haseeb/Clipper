"""Read generated clips back from data/insta_vid and data/yt_vids."""

from __future__ import annotations

import json
from pathlib import Path

from clipper import config


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _safe_dir(root: Path, slug: str) -> Path | None:
    d = (root / slug).resolve()
    return d if d.parent == root.resolve() else None


def list_videos() -> list[dict]:
    """One entry per processed source video, newest first."""
    slugs = {p.name for root in (config.INSTA_DIR, config.YT_DIR) if root.exists()
             for p in root.iterdir() if p.is_dir()}
    items = []
    for slug in slugs:
        jsons = sorted((config.INSTA_DIR / slug).glob("*.json")) or sorted((config.YT_DIR / slug).glob("*.json"))
        if not jsons:
            continue
        src = _read_json(jsons[0]).get("source_video") or {}
        items.append({
            "slug": slug,
            "title": src.get("title") or slug,
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
    """All clips for one source video, with Instagram and YouTube metadata merged.
    File URLs are built as {media_prefix}/insta_vid/<slug>/<file>."""
    insta_dir, yt_dir = _safe_dir(config.INSTA_DIR, slug), _safe_dir(config.YT_DIR, slug)
    if insta_dir is None or yt_dir is None:
        return None
    names = sorted({p.stem for d in (insta_dir, yt_dir) if d.exists() for p in d.glob("*.json")})
    if not names:
        return None

    def url(folder: str, d: Path, file: str) -> str | None:
        return f"{media_prefix}/{folder}/{slug}/{file}" if (d / file).exists() else None

    clips = []
    for name in names:
        ig = _read_json(insta_dir / f"{name}.json")
        yt = _read_json(yt_dir / f"{name}.json")
        base = ig or yt
        clips.append({
            **{k: base.get(k) for k in ("clip_number", "working_title", "summary", "hook", "reason",
                                        "transcript", "start", "end", "duration_sec", "format",
                                        "created_at", "source_video")},
            "name": name,
            "instagram": {
                "caption": ig.get("caption"),
                "hashtags": ig.get("hashtags") or [],
                "full_caption": ig.get("full_caption"),
                "video": url("insta_vid", insta_dir, f"{name}.mp4"),
                "json": url("insta_vid", insta_dir, f"{name}.json"),
            } if ig else None,
            "youtube": {
                "title": yt.get("title"),
                "description": yt.get("description"),
                "tags": yt.get("tags") or [],
                "hashtags": yt.get("hashtags") or [],
                "full_description": yt.get("full_description"),
                "video": url("yt_vids", yt_dir, f"{name}.mp4"),
                "json": url("yt_vids", yt_dir, f"{name}.json"),
            } if yt else None,
        })
    src = clips[0].get("source_video") or {}
    return {"slug": slug, "title": src.get("title") or slug, "source_video": src, "clips": clips}
