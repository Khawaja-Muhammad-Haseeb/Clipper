"""Read generated clips back from data/clips/<slug>/."""

from __future__ import annotations

import json
import re
from pathlib import Path

from clipper import config, outro
from clipper.errors import ClipperError
from clipper.media import join, probe
from clipper.reporting import log


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
        ends = {pl: f"{media_prefix}/clips/{slug}/{f}" for pl, f in (c.get("end_screens") or {}).items()
                if (d / f).exists()}
        c["end_screens"] = ends or None
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


def export(slug: str, name: str, platform: str | None, dst: Path) -> Path:
    """Write the clip, with the platform's end screen appended if it has one, to dst."""
    d = _video_dir(slug)
    if not re.fullmatch(r"[\w-]+", name):
        raise ClipperError("Clip not found")
    meta = _read_json(d / f"{name}.json") if d else {}
    if not meta:
        raise ClipperError("Clip not found")
    clip = d / (meta.get("video_file") or f"{name}.mp4")
    end_file = (meta.get("end_screens") or {}).get(platform or "")
    if not end_file or not (d / end_file).exists():
        dst.write_bytes(clip.read_bytes())
        return dst
    # Clips made by this version share the end screen's encoding settings: instant join.
    join([clip, d / end_file], dst, copy=meta.get("encoding") == 2)
    return dst


def add_missing_end_screens() -> int:
    """Create end screens for library clips that don't have them (skips 'original' format)."""
    made = 0
    for d in sorted(config.CLIPS_DIR.iterdir()) if config.CLIPS_DIR.exists() else []:
        for path in sorted(d.glob("*.json")):
            meta = _read_json(path)
            if not meta or meta.get("end_screens"):
                continue
            clip = d / (meta.get("video_file") or f"{path.stem}.mp4")
            if not clip.exists() or probe(clip)[1:] != (outro.W, outro.H):
                continue
            log(f"End screens: {d.name}/{clip.name}")
            meta["end_screens"] = outro.add_end_pieces(clip, config.OUTRO_HANDLE)
            path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            made += 1
    log(f"Added end screens to {made} clips.")
    return made
