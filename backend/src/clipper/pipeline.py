"""The clip pipeline: get video -> transcribe -> pick clips -> captions -> cut & save."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

from clipper import analysis, config, llm
from clipper.errors import ClipperError
from clipper.media import cut_clip, probe
from clipper.reporting import log, progress
from clipper.schemas import ClipMeta, ClipOptions, ClipPick
from clipper.transcribe import Segment, format_for_llm, transcribe
from clipper.utils import seconds_to_ts, slugify, ts_to_seconds
from clipper.youtube import get_video


def run(source: str, opts: ClipOptions, client: OpenAI | None = None) -> dict:
    """Process one video. Returns {"slug", "title", "clips": [clip names]}."""
    client = client or llm.client()

    progress("download", 0.0)
    video, meta = get_video(source)
    progress("download", 1.0)
    duration, w, h = probe(video)
    log(f"Video: {meta['title']} ({seconds_to_ts(duration)}, {w}x{h})")

    slug = slugify(meta["title"])
    work = config.WORK_DIR / slug
    work.mkdir(parents=True, exist_ok=True)

    segments = _transcript(video, work, duration)
    picks = _clip_picks(client, segments, meta, duration, work, opts)

    log("Writing captions, titles and hashtags...")
    progress("captions", None, "Waiting for the model")
    metas = analysis.describe_clips(client, picks, meta)
    progress("captions", 1.0)

    saved = _cut_and_save(video, picks, metas, meta, slug, work, opts, w, h)
    log("Done!")
    log(f"  Instagram clips: {config.INSTA_DIR / slug}")
    log(f"  YouTube clips:   {config.YT_DIR / slug}")
    return {"slug": slug, "title": meta["title"], "clips": saved}


# ---- Steps ------------------------------------------------------------------
def _transcript(video: Path, work: Path, duration: float) -> list[Segment]:
    """Transcribe once; cached in work/<slug>/transcript.json."""
    cache = work / "transcript.json"
    if cache.exists():
        segments = json.loads(cache.read_text(encoding="utf-8"))
        log(f"Reusing saved transcript ({len(segments)} segments)")
    else:
        progress("transcribe", 0.0)
        segments = transcribe(video, work, duration)
        if not segments:
            raise ClipperError("Whisper found no speech in this video.")
        cache.write_text(json.dumps(segments, indent=1, ensure_ascii=False), encoding="utf-8")
    progress("transcribe", 1.0)
    return segments


def _clip_picks(client: OpenAI, segments: list[Segment], meta: dict, duration: float,
                work: Path, opts: ClipOptions) -> list[dict]:
    """Ask the LLM for clips; cached in work/<slug>/clip_picks.json unless opts.fresh."""
    cache = work / "clip_picks.json"
    if cache.exists() and not opts.fresh:
        picks = json.loads(cache.read_text(encoding="utf-8"))
        log("Reusing saved clip picks (use fresh / --fresh to redo)")
    else:
        log("Asking the LLM to pick clips from the transcript...")
        progress("pick", None, "Waiting for the model")
        raw = analysis.find_clips(client, format_for_llm(segments), meta, duration, opts)
        picks = snap_picks(raw, segments, duration, opts)
        cache.write_text(json.dumps(picks, indent=2, ensure_ascii=False), encoding="utf-8")
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


def _cut_and_save(video: Path, picks: list[dict], metas: dict[int, ClipMeta], meta: dict,
                  slug: str, work: Path, opts: ClipOptions, w: int, h: int) -> list[str]:
    insta_out, yt_out = config.INSTA_DIR / slug, config.YT_DIR / slug
    for folder in (insta_out, yt_out):
        folder.mkdir(parents=True, exist_ok=True)
        # Re-running a video replaces its clips instead of mixing old and new ones.
        for old in folder.glob("clip_*.*"):
            old.unlink()

    saved: list[str] = []
    n = len(picks)
    progress("cut", 0.0, f"0 / {n}")
    for i, pick in enumerate(picks, 1):
        cm = metas.get(i)
        if cm is None:
            log(f"[{i}/{n}] No captions returned for this clip; skipping")
            continue
        name = f"clip_{i:02d}_{slugify(cm.name, 40)}"
        tmp_clip = work / f"{name}.mp4"
        log(f"[{i}/{n}] Cutting {seconds_to_ts(pick['start_sec'])}-{seconds_to_ts(pick['end_sec'])} -> {name}")
        cut_clip(video, tmp_clip, pick["start_sec"], pick["end_sec"], opts.format, w, h)

        base = {
            "name": name,
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
            "source_video": meta,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "uploaded": False,
        }
        ig, yt = cm.instagram, cm.youtube
        targets = [
            (insta_out, {**base, "platform": "instagram", "caption": ig.caption, "hashtags": ig.hashtags,
                         "full_caption": f"{ig.caption}\n\n{' '.join(ig.hashtags)}"}),
            (yt_out, {**base, "platform": "youtube", "title": yt.title, "description": yt.description,
                      "tags": yt.tags, "hashtags": yt.hashtags,
                      "full_description": f"{yt.description}\n\n{' '.join(yt.hashtags)}"}),
        ]
        for folder, data in targets:
            shutil.copyfile(tmp_clip, folder / f"{name}.mp4")
            data["video_file"] = f"{name}.mp4"
            (folder / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                                 encoding="utf-8")
        tmp_clip.unlink(missing_ok=True)
        saved.append(name)
        progress("cut", i / n, f"{i} / {n}")

    progress("cut", 1.0, f"{len(saved)} clips saved")
    return saved
