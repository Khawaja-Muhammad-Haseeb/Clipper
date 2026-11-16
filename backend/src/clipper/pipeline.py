"""The clip pipeline.

  1. resolve      identify the video (no download yet)
  2. transcribe   cached in data/work/<slug>/transcript.json   (needs the video once)
  3. pick clips   cached in data/work/<slug>/clip_picks.json   (transcript only)
  4. captions     one LLM request for all clips                (transcript only)
  5. cut & save   data/clips/<slug>/clip_XX_<name>.mp4 + .json (needs the video)
  6. clean up     delete the downloaded / uploaded source video

Because steps 3-4 only need the transcript, making new clips from a video processed
before skips transcription, picks the clips first, and only then downloads the video
again for cutting.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

from clipper import analysis, backgrounds, config, llm, youtube
from clipper.errors import ClipperError
from clipper.media import cut_clip, needs_background, probe
from clipper.reporting import log, progress
from clipper.schemas import ClipMeta, ClipOptions, ClipPick
from clipper.transcribe import Segment, format_for_llm, transcribe
from clipper.utils import seconds_to_ts, slugify, ts_to_seconds


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class SourceVideo:
    """The source video file, downloaded only when a step actually needs it."""

    def __init__(self, path: Path | None, meta: dict):
        self.path = path
        self.meta = meta

    def get(self, stage: str) -> Path:
        if self.path and self.path.exists():
            return self.path
        if not self.meta.get("url"):
            raise ClipperError("The source file no longer exists. Upload or select it again.")

        def on_progress(frac: float, speed: str | None) -> None:
            if stage == "download":
                progress("download", frac, speed)
            else:  # downloading again during the cut stage (re-clipping)
                progress(stage, None, f"Downloading video {int(frac * 100)}%")

        self.path = youtube.download(self.meta["url"], self.meta["id"], on_progress)
        return self.path

    def delete_if_temporary(self) -> None:
        """Delete the source if we created it (download or upload), never the user's own files."""
        if not self.path or not self.path.exists():
            return
        if not self.path.resolve().is_relative_to(config.DOWNLOADS_DIR.resolve()):
            return
        size_mb = self.path.stat().st_size / 1e6
        self.path.unlink()
        log(f"Deleted source video ({size_mb:.0f} MB). The transcript is kept for re-clipping.")


def run(source: str, opts: ClipOptions, client: OpenAI | None = None) -> dict:
    """Process one video. Returns {"slug", "title", "clips": [clip names]}."""
    client = client or llm.client()
    if needs_background(opts.format):
        backgrounds.Picker()  # fail now, not after downloading and transcribing, if there are none

    progress("download", None, "Reading video info")
    path, meta = youtube.resolve(source)
    video = SourceVideo(path, meta)
    log(f"Video: {meta['title']}" + (f" ({seconds_to_ts(meta['duration'])})" if meta.get("duration") else ""))

    slug = slugify(meta["title"])
    work = config.WORK_DIR / slug
    work.mkdir(parents=True, exist_ok=True)
    _write_json(work / "source.json", meta)

    segments = _transcript(video, work)
    duration = float(meta.get("duration") or segments[-1]["end"])
    picks = _clip_picks(client, segments, meta, duration, work, opts)

    log("Writing captions, titles and hashtags...")
    progress("captions", None, "Waiting for the model")
    metas = analysis.describe_clips(client, picks, meta)
    progress("captions", 1.0)

    saved = _cut_and_save(video, picks, metas, meta, slug, work, opts)

    if not opts.keep_source:
        video.delete_if_temporary()
    log("Done!")
    log(f"  Clips: {config.CLIPS_DIR / slug}")
    return {"slug": slug, "title": meta["title"], "clips": saved}


# ---- Steps ------------------------------------------------------------------
def _transcript(video: SourceVideo, work: Path) -> list[Segment]:
    cache = work / "transcript.json"
    if cache.exists():
        segments = json.loads(cache.read_text(encoding="utf-8"))
        log(f"Reusing saved transcript ({len(segments)} segments); the video is only needed for cutting")
        progress("download", 1.0, "Later, for cutting")
        progress("transcribe", 1.0, "Saved transcript")
        return segments

    path = video.get("download")
    progress("download", 1.0)
    duration, _, _ = probe(path)
    video.meta["duration"] = duration
    progress("transcribe", 0.0)
    segments = transcribe(path, work, duration)
    if not segments:
        raise ClipperError("Whisper found no speech in this video.")
    _write_json(cache, segments)
    progress("transcribe", 1.0)
    return segments


def _clip_picks(client: OpenAI, segments: list[Segment], meta: dict, duration: float,
                work: Path, opts: ClipOptions) -> list[dict]:
    cache = work / "clip_picks.json"
    if cache.exists() and not opts.fresh:
        picks = json.loads(cache.read_text(encoding="utf-8"))
        log("Reusing saved clip picks (use fresh / --fresh to pick new ones)")
    else:
        log("Asking the LLM to pick clips from the transcript...")
        progress("pick", None, "Waiting for the model")
        raw = analysis.find_clips(client, format_for_llm(segments), meta, duration, opts)
        picks = snap_picks(raw, segments, duration, opts)
        _write_json(cache, picks)
    if not picks:
        raise ClipperError("No usable clips were returned. Try again with fresh picks or another model.")
    progress("pick", 1.0, f"{len(picks)} clips")
    log(f"{len(picks)} clips selected:")
    for i, p in enumerate(picks, 1):
        log(f"  {i}. {seconds_to_ts(p['start_sec'])}-{seconds_to_ts(p['end_sec'])}  {p['title']}")
    return picks


def snap_picks(picks: list[ClipPick], segments: list[Segment], duration: float,
               opts: ClipOptions) -> list[dict]:
    """Snap clip edges to sentence boundaries; drop invalid, too-short or overlapping clips."""
    out, last_end = [], -1.0
    for p in picks:
        try:
            s, e = ts_to_seconds(p.start), ts_to_seconds(p.end)
        except ValueError:
            log(f"  Skipping clip with bad timestamps: {p.start} - {p.end}")
            continue
        if segments:
            # Start at the segment start nearest the suggested start...
            s = min((seg["start"] for seg in segments), key=lambda t: abs(t - s))
            # ...end at the segment end nearest the suggested end, within the max length.
            ends = [seg["end"] for seg in segments if s + 3 < seg["end"] <= s + opts.max_len + 2]
            if ends:
                e = min(ends, key=lambda t: abs(t - e))
        s, e = max(0.0, s), min(duration, e)
        if e - s > opts.max_len + 2:
            e = s + opts.max_len
        if e - s < max(5, opts.min_len * 0.5) or s < last_end:
            log(f"  Skipping '{p.title}' ({p.start}-{p.end}): too short or overlapping")
            continue
        text = " ".join(seg["text"] for seg in segments if seg["start"] >= s - 0.5 and seg["end"] <= e + 0.5)
        out.append({**p.model_dump(), "start_sec": round(s, 2), "end_sec": round(e, 2), "transcript": text})
        last_end = e
    return out


def _cut_and_save(video: SourceVideo, picks: list[dict], metas: dict[int, ClipMeta], meta: dict,
                  slug: str, work: Path, opts: ClipOptions) -> list[str]:
    n = len(picks)
    progress("cut", None if not (video.path and video.path.exists()) else 0.0, f"0 / {n}")
    src = video.get("cut")
    _, w, h = probe(src)

    picker = backgrounds.Picker() if needs_background(opts.format) else None

    out_dir = config.CLIPS_DIR / slug
    if out_dir.exists():  # re-running a video replaces its clips
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    saved: list[str] = []
    for i, pick in enumerate(picks, 1):
        cm = metas.get(i)
        if cm is None:
            log(f"[{i}/{n}] No captions returned for this clip; skipping")
            continue
        # Models sometimes prefix their own "clip_1_"; we add the number ourselves.
        short = re.sub(r"^(clip_?\d*_?)+", "", slugify(cm.name, 60)) or "clip"
        name = f"clip_{i:02d}_{short[:40].strip('_')}"
        log(f"[{i}/{n}] Cutting {seconds_to_ts(pick['start_sec'])}-{seconds_to_ts(pick['end_sec'])} -> {name}")
        bg = picker.next(pick["end_sec"] - pick["start_sec"]) if picker else None
        if bg:
            log(f"    background: {bg[0].stem} from {seconds_to_ts(bg[1])}")
        cut_clip(src, out_dir / f"{name}.mp4", pick["start_sec"], pick["end_sec"], opts.format, w, h, bg)

        ig, yt = cm.instagram, cm.youtube
        _write_json(out_dir / f"{name}.json", {
            "name": name,
            "video_file": f"{name}.mp4",
            "clip_number": i,
            "working_title": pick["title"],
            "summary": cm.summary,
            "hook": pick["hook"],
            "reason": pick["reason"],
            "transcript": pick["transcript"],
            "start": seconds_to_ts(pick["start_sec"]),
            "end": seconds_to_ts(pick["end_sec"]),
            "duration_sec": round(pick["end_sec"] - pick["start_sec"], 2),
            "format": opts.format,
            "background": {"id": bg[0].stem, "start_sec": round(bg[1], 1)} if bg else None,
            "source_video": meta,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "instagram": {
                "caption": ig.caption,
                "hashtags": ig.hashtags,
                "full_caption": f"{ig.caption}\n\n{' '.join(ig.hashtags)}",
                "uploaded": False,
            },
            "youtube": {
                "title": yt.title,
                "description": yt.description,
                "tags": yt.tags,
                "hashtags": yt.hashtags,
                "full_description": f"{yt.description}\n\n{' '.join(yt.hashtags)}",
                "uploaded": False,
            },
        })
        saved.append(name)
        progress("cut", i / n, f"{i} / {n}")

    progress("cut", 1.0, f"{len(saved)} clips saved")
    return saved
