"""Background videos (gameplay, satisfying clips...) placed behind / below clips.

Stored in data/backgrounds/<id>.mp4 with a <id>.json sidecar. Each is a ~2 minute,
video-only section downloaded from a YouTube video whose uploader marks it as
no-copyright / free to use, or a file you add yourself.
"""

from __future__ import annotations

import json
import random
import re
import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import yt_dlp
from yt_dlp.utils import download_range_func

from clipper import config
from clipper.errors import ClipperError
from clipper.media import ffmpeg, ffmpeg_dir, probe
from clipper.reporting import log
from clipper.utils import slugify

SECTION_SEC = 120  # length of each background

# Searches used by "download random backgrounds". Results must claim to be free to use.
SEARCHES = [
    "minecraft parkour gameplay no copyright free to use",
    "subway surfers gameplay no copyright free to use",
    "gta 5 gameplay no copyright free to use",
    "satisfying video no copyright free to use",
    "trackmania gameplay no copyright",
    "fortnite gameplay no copyright free to use",
    "temple run gameplay no copyright",
    "soap cutting asmr no copyright",
    "kinetic sand satisfying no copyright",
    "rocket league gameplay no copyright free to use",
]
FREE_TO_USE = re.compile(r"no[\s-]*copyright|copyright[\s-]*free|free[\s-]*to[\s-]*use|non[\s-]*copyright|royalty[\s-]*free", re.I)
_BASE = {"quiet": True, "no_warnings": True, "noprogress": True}


def _dir() -> Path:
    config.BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)
    return config.BACKGROUNDS_DIR


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def thumbnail(video: Path) -> Path | None:
    """<id>.jpg preview frame, created on first use."""
    thumb = video.with_suffix(".jpg")
    if not thumb.exists():
        try:
            ffmpeg("-ss", "5", "-i", str(video), "-frames:v", "1", "-vf", "scale=480:-2", "-q:v", "4", str(thumb))
        except ClipperError:
            return None
    return thumb


def list_all() -> list[dict]:
    items = []
    for video in sorted(_dir().glob("*.mp4")):
        meta = _read(video.with_suffix(".json"))
        thumb = thumbnail(video)
        items.append({
            "id": video.stem,
            "file": video.name,
            "thumb": thumb.name if thumb else None,
            "title": meta.get("title") or video.stem,
            "channel": meta.get("channel"),
            "url": meta.get("url"),
            "duration": meta.get("duration"),
            "added": meta.get("added"),
            "size_mb": round(video.stat().st_size / 1e6, 1),
        })
    return items


def delete(bg_id: str) -> bool:
    video = (_dir() / f"{bg_id}.mp4").resolve()
    if video.parent != _dir().resolve() or not video.exists():
        return False
    video.unlink()
    video.with_suffix(".json").unlink(missing_ok=True)
    video.with_suffix(".jpg").unlink(missing_ok=True)
    return True


def compress(video: Path) -> None:
    """Re-encode in place: max 720p, 30 fps, no audio. Backgrounds are shown blurred or in
    half the frame, so the lower quality isn't visible in the final clip."""
    tmp = video.with_name(video.stem + ".tmp.mp4")
    ffmpeg("-i", str(video), "-an", "-vf", "fps=30,scale=-2:'min(720,ih)'",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "32", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(tmp))
    if tmp.stat().st_size < video.stat().st_size:
        tmp.replace(video)
    else:  # already small (e.g. low-motion video): keep the original
        tmp.unlink()


def _save_meta(bg_id: str, **meta) -> None:
    meta["added"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (_dir() / f"{bg_id}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def add_file(path: Path, title: str | None = None) -> dict:
    """Add a local video file as a background (copied into data/backgrounds)."""
    bg_id = f"file_{slugify(path.stem, 40)}"
    dest = _dir() / f"{bg_id}.mp4"
    shutil.copyfile(path, dest)
    compress(dest)
    duration, _, _ = probe(dest)
    _save_meta(bg_id, title=title or path.stem, channel=None, url=None, duration=round(duration, 1))
    return {"id": bg_id}


def add_from_youtube(url: str, section: int = SECTION_SEC) -> dict:
    """Download a ~2 min, video-only, 720p section of a YouTube video, skipping the intro."""
    with yt_dlp.YoutubeDL(_BASE) as ydl:
        info = ydl.extract_info(url, download=False)
    total = info.get("duration") or 0
    if total and total <= section + 20:
        start = 0.0
    else:
        # Random 2 minutes, skipping the first 10% (intros, channel promos) and the end.
        lo = min(60.0, total * 0.1)
        start = random.uniform(lo, max(lo, total - section - 15))
    bg_id = f"yt_{info['id']}"
    opts = {
        **_BASE,
        "format": "bv*[height<=720][vcodec^=avc1]/bv*[height<=720][ext=mp4]/bv*[height<=720]/bv*",
        "outtmpl": str(_dir() / f"{bg_id}.%(ext)s"),
        "ffmpeg_location": ffmpeg_dir(),
        "download_ranges": download_range_func(None, [(start, start + section)]),
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    files = [p for p in _dir().glob(f"{bg_id}.*") if p.suffix != ".json"]
    if not files:
        raise ClipperError(f"Download failed for {url}")
    video = files[0]
    if video.suffix != ".mp4":
        video = video.rename(video.with_suffix(".mp4"))
    compress(video)
    duration, _, _ = probe(video)
    _save_meta(bg_id, title=info.get("title"), channel=info.get("channel") or info.get("uploader"),
               url=info.get("webpage_url") or url, duration=round(duration, 1),
               section_start=round(start, 1))
    return {"id": bg_id, "title": info.get("title")}


def find_candidates(count: int, exclude: set[str]) -> list[dict]:
    """Search YouTube for videos whose titles say they're free to use, mixing categories."""
    searches = SEARCHES[:]
    random.shuffle(searches)
    picked: list[dict] = []
    per_search = max(1, -(-count // len(searches)) + 1)
    with yt_dlp.YoutubeDL({**_BASE, "extract_flat": True}) as ydl:
        for q in searches:
            if len(picked) >= count:
                break
            entries = ydl.extract_info(f"ytsearch12:{q}", download=False).get("entries") or []
            ok = [e for e in entries
                  if e.get("id") and f"yt_{e['id']}" not in exclude
                  and FREE_TO_USE.search(e.get("title") or "")
                  and (e.get("duration") or 0) >= 90           # long enough for a 2 min section
                  and (e.get("duration") or 0) <= 4 * 3600]
            random.shuffle(ok)
            for e in ok[:per_search]:
                if len(picked) < count and all(p["id"] != e["id"] for p in picked):
                    picked.append({"id": e["id"], "title": e.get("title"), "query": q,
                                   "url": f"https://www.youtube.com/watch?v={e['id']}"})
    return picked


def download_random(count: int,
                    on_progress: Callable[[int, int, str], None] | None = None) -> list[dict]:
    """Find and download `count` new random free-to-use backgrounds."""
    existing = {b["id"] for b in list_all()}
    log(f"Searching YouTube for {count} free-to-use background videos...")
    candidates = find_candidates(count, existing)
    added = []
    for i, c in enumerate(candidates, 1):
        if on_progress:
            on_progress(i - 1, len(candidates), c["title"])
        log(f"  [{i}/{len(candidates)}] {c['title']}")
        try:
            added.append(add_from_youtube(c["url"]))
        except Exception as e:  # noqa: BLE001 - skip this one, keep going
            log(f"    skipped: {e}")
    if on_progress:
        on_progress(len(candidates), len(candidates), "Done")
    return added


class Picker:
    """Hands out backgrounds for the clips of one video: random, no repeats until all are used."""

    def __init__(self) -> None:
        self.pool: list[Path] = []
        self.files = sorted(_dir().glob("*.mp4"))
        if not self.files:
            raise ClipperError("No background videos yet. Add some on the Backgrounds page "
                               "or run `clipper --download-backgrounds 12`.")

    def next(self, clip_duration: float) -> tuple[Path, float]:
        """Returns (background file, start offset) so that a clip_duration slice fits inside it."""
        if not self.pool:
            self.pool = self.files[:]
            random.shuffle(self.pool)
        bg = self.pool.pop()
        meta = _read(bg.with_suffix(".json"))
        duration = meta.get("duration") or probe(bg)[0]
        start = random.uniform(0, duration - clip_duration) if duration > clip_duration else 0.0
        return bg, start
