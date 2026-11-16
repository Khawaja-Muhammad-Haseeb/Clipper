"""
Clipper - turn a long video into short clips using free / open-source models.

Pipeline:
  1. Download the video with yt-dlp (or use a local file)
  2. Transcribe it with Whisper (Groq's free API, or locally with faster-whisper)
  3. An open-source LLM reads the timestamped transcript and picks the best clips
  4. Clip boundaries are snapped to sentence boundaries, ffmpeg cuts them (9:16)
  5. The LLM writes captions / titles / hashtags for every clip
  6. Clips + one JSON file per clip are saved to insta_vid/ and yt_vids/

The LLM can be any OpenAI-compatible endpoint: OpenRouter, Groq, Ollama, LM Studio...

Usage:
  python clipper.py "https://www.youtube.com/watch?v=..."
  python clipper.py path/to/video.mp4
  python clipper.py --list-models
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import imageio_ffmpeg
from dotenv import load_dotenv
from openai import OpenAI, APIStatusError
from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parent
DOWNLOADS = ROOT / "downloads"
WORK = ROOT / "work"
INSTA_DIR = ROOT / "insta_vid"
YT_DIR = ROOT / "yt_vids"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

load_dotenv(ROOT / ".env")

# Windows consoles default to cp1252; don't crash on emoji in titles / descriptions.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

# Transcription: "groq" (free API, fast) or "local" (faster-whisper on your CPU, unlimited, slower)
TRANSCRIBE = os.getenv("TRANSCRIBE", "groq" if os.getenv("GROQ_API_KEY") else "local").lower()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
LOCAL_WHISPER_MODEL = os.getenv("LOCAL_WHISPER_MODEL", "small")

# LLM: any OpenAI-compatible endpoint. Defaults to OpenRouter.
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
# Comma-separated list; the next model is tried if one is rate-limited or fails.
LLM_MODELS = [m.strip() for m in os.getenv("LLM_MODEL", "").split(",") if m.strip()]


# --------------------------------------------------------------------------- #
# Schemas the LLM must answer with
# --------------------------------------------------------------------------- #
class ClipPick(BaseModel):
    start: str
    end: str
    title: str
    hook: str = ""
    reason: str = ""


class ClipPicks(BaseModel):
    clips: list[ClipPick]


class InstagramMeta(BaseModel):
    caption: str
    hashtags: list[str]


class YouTubeMeta(BaseModel):
    title: str
    description: str
    tags: list[str]
    hashtags: list[str]


class ClipMeta(BaseModel):
    clip_number: int
    name: str
    summary: str
    instagram: InstagramMeta
    youtube: YouTubeMeta


class ClipMetas(BaseModel):
    clips: list[ClipMeta]


class TopicMatch(BaseModel):
    video_number: int
    relevant: bool
    reason: str = ""


class TopicMatches(BaseModel):
    results: list[TopicMatch]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def slugify(text: str, max_len: int = 50) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:max_len].strip("_") or "video"


def ts_to_seconds(ts) -> float:
    if isinstance(ts, (int, float)):
        return float(ts)
    secs = 0.0
    for p in str(ts).strip().split(":"):
        secs = secs * 60 + float(p)
    return secs


def seconds_to_ts(secs: float) -> str:
    secs = int(round(secs))
    return f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"


def ffmpeg(*args: str) -> None:
    res = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args],
                         capture_output=True, text=True, errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {res.stderr.strip()}")


def probe(path: Path) -> tuple[float, int, int]:
    """Return (duration_seconds, width, height) by parsing ffmpeg's output."""
    out = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)],
                         capture_output=True, text=True, errors="replace").stderr
    d = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    v = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", out)
    if not d or not v:
        sys.exit(f"Could not read video info from {path}")
    return int(d[1]) * 3600 + int(d[2]) * 60 + float(d[3]), int(v[1]), int(v[2])


# --------------------------------------------------------------------------- #
# Step 1: get the video
# --------------------------------------------------------------------------- #
def download(url: str) -> tuple[Path, dict]:
    import yt_dlp

    DOWNLOADS.mkdir(exist_ok=True)
    opts = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(DOWNLOADS / "%(id)s.%(ext)s"),
        "ffmpeg_location": FFMPEG,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        path = DOWNLOADS / f"{info['id']}.mp4"
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
    local = Path(source)
    if local.exists():
        return local.resolve(), {"id": slugify(local.stem), "title": local.stem,
                                 "channel": None, "url": None, "description": ""}
    return download(source)


# --------------------------------------------------------------------------- #
# Step 2: transcribe
# --------------------------------------------------------------------------- #
def transcribe_groq(video: Path, work: Path, duration: float) -> list[dict]:
    if not GROQ_API_KEY:
        sys.exit("TRANSCRIBE=groq but GROQ_API_KEY is not set in .env")
    client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1", max_retries=3)
    chunk_len = 1800  # 30 min of 16 kHz mono 48 kbps mp3 ~ 11 MB, under Groq's 25 MB limit
    segments: list[dict] = []
    offset = 0.0
    while offset < duration:
        audio = work / f"audio_{int(offset)}.mp3"
        ffmpeg("-ss", str(offset), "-t", str(chunk_len), "-i", str(video),
               "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(audio))
        log(f"  Transcribing {seconds_to_ts(offset)} - {seconds_to_ts(min(duration, offset + chunk_len))} (Groq)")
        with open(audio, "rb") as f:
            resp = client.audio.transcriptions.create(
                file=(audio.name, f.read()), model=GROQ_WHISPER_MODEL,
                response_format="verbose_json", timestamp_granularities=["segment"])
        data = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        for s in data.get("segments") or []:
            segments.append({"start": round(s["start"] + offset, 2),
                             "end": round(s["end"] + offset, 2),
                             "text": s["text"].strip()})
        audio.unlink(missing_ok=True)
        offset += chunk_len
    return segments


def transcribe_local(video: Path, duration: float) -> list[dict]:
    from faster_whisper import WhisperModel

    log(f"  Loading local Whisper model '{LOCAL_WHISPER_MODEL}' (first run downloads it)")
    model = WhisperModel(LOCAL_WHISPER_MODEL, device="cpu", compute_type="int8")
    # Decode audio with our bundled ffmpeg (16 kHz mono float32) instead of PyAV.
    import numpy as np
    raw = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(video),
                          "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    seg_iter, _ = model.transcribe(audio, vad_filter=True, beam_size=1)
    segments, last_report = [], 0.0
    for s in seg_iter:
        segments.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()})
        if s.end - last_report > 120:
            log(f"  Transcribed {seconds_to_ts(s.end)} / {seconds_to_ts(duration)}")
            last_report = s.end
    return segments


def transcript_for_llm(segments: list[dict], block: float = 10.0) -> str:
    """Merge Whisper segments into ~10 s lines like '[00:12:30] text' to save tokens."""
    lines, cur_start, cur_text = [], None, []
    for s in segments:
        if cur_start is None:
            cur_start = s["start"]
        cur_text.append(s["text"])
        if s["end"] - cur_start >= block:
            lines.append(f"[{seconds_to_ts(cur_start)}] {' '.join(cur_text)}")
            cur_start, cur_text = None, []
    if cur_text:
        lines.append(f"[{seconds_to_ts(cur_start)}] {' '.join(cur_text)}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# LLM calls (OpenAI-compatible, with model fallback)
# --------------------------------------------------------------------------- #
def llm_client() -> OpenAI:
    if not LLM_API_KEY and "localhost" not in LLM_BASE_URL and "127.0.0.1" not in LLM_BASE_URL:
        sys.exit("LLM_API_KEY is not set in .env")
    return OpenAI(api_key=LLM_API_KEY or "none", base_url=LLM_BASE_URL, max_retries=2, timeout=600)


def extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)   # reasoning models
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model response")
    return json.loads(text[start:end + 1])


def ask_llm(client: OpenAI, system: str, user: str, schema: type[BaseModel], temperature: float):
    """Try each configured model in turn until one returns valid JSON for `schema`."""
    if not LLM_MODELS:
        sys.exit("LLM_MODEL is not set in .env. Run `python clipper.py --list-models` to pick one.")
    errors = []
    for model in LLM_MODELS:
        for use_json_mode in (True, False):
            try:
                kwargs = {"response_format": {"type": "json_object"}} if use_json_mode else {}
                resp = client.chat.completions.create(
                    model=model, temperature=temperature,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}], **kwargs)
                return schema.model_validate(extract_json(resp.choices[0].message.content)), model
            except APIStatusError as e:
                # Some providers reject json mode -> retry once without it.
                if e.status_code == 400 and use_json_mode:
                    continue
                errors.append(f"{model}: HTTP {e.status_code} {str(e.message)[:200]}")
                log(f"  {model} failed (HTTP {e.status_code}); trying next model")
                break
            except (ValueError, ValidationError) as e:
                errors.append(f"{model}: bad JSON ({str(e)[:150]})")
                log(f"  {model} returned unusable JSON; {'retrying' if use_json_mode else 'trying next model'}")
    raise RuntimeError("All models failed:\n  " + "\n  ".join(errors))


JSON_ONLY = "You reply with a single valid JSON object and nothing else."


def find_clips(client, transcript: str, meta: dict, duration: float, args) -> list[ClipPick]:
    prompt = f"""You are an expert short-form video editor who finds viral moments for
Instagram Reels and YouTube Shorts.

Below is the timestamped transcript of a video (total length {seconds_to_ts(duration)}).
Pick the {args.min_clips}-{args.max_clips} BEST self-contained moments to turn into short clips.

Video title: {meta.get('title')}
Channel: {meta.get('channel') or 'unknown'}

Rules for each clip:
- Between {args.min_len} and {args.max_len} seconds long.
- Must make sense on its own without the rest of the video.
- Start right at a strong hook (bold statement, question, surprising moment), never mid-sentence.
- End on a complete thought or punchline, never mid-sentence.
- Clips must not overlap. Return them in chronological order.
- Prefer emotion, insight, humor, controversy, strong opinions or a clear takeaway.
- Use timestamps from the transcript, format HH:MM:SS.

Respond with JSON exactly in this shape:
{{"clips": [{{"start": "HH:MM:SS", "end": "HH:MM:SS", "title": "short working title",
  "hook": "the opening line that grabs attention", "reason": "why this will perform well"}}]}}

TRANSCRIPT:
{transcript}"""
    picks, model = ask_llm(client, JSON_ONLY, prompt, ClipPicks, temperature=0.4)
    log(f"  Clips picked by {model}")
    return picks.clips


def describe_clips(client, picks: list[dict], meta: dict) -> dict[int, ClipMeta]:
    clips_txt = "\n\n".join(
        f"CLIP {i}\nWorking title: {p['title']}\nHook: {p['hook']}\nTranscript: {p['transcript']}"
        for i, p in enumerate(picks, 1))
    prompt = f"""Write publishing metadata for each of these short clips cut from the video
"{meta.get('title')}"{f" by {meta['channel']}" if meta.get('channel') else ''}.

For every clip write metadata for BOTH an Instagram Reel and a YouTube Short.
Make it punchy and native to each platform. Only use facts that are in the clip transcript.

- instagram.caption: hook as the first line, 1-3 short lines, then a call to action
- instagram.hashtags: 8-15 relevant hashtags, each starting with #
- youtube.title: under 70 characters, curiosity-driven
- youtube.description: 2-4 sentences
- youtube.tags: 10-15 search keywords without #
- youtube.hashtags: 3-5 hashtags starting with #, include #shorts
- name: short snake_case file name for the clip
- summary: one sentence describing the clip

Respond with JSON exactly in this shape:
{{"clips": [{{"clip_number": 1, "name": "...", "summary": "...",
  "instagram": {{"caption": "...", "hashtags": ["#..."]}},
  "youtube": {{"title": "...", "description": "...", "tags": ["..."], "hashtags": ["#shorts"]}}}}]}}

{clips_txt}"""
    metas, model = ask_llm(client, JSON_ONLY, prompt, ClipMetas, temperature=0.8)
    log(f"  Captions written by {model}")
    return {m.clip_number: m for m in metas.clips}


# --------------------------------------------------------------------------- #
# Clip cleanup: snap to sentence boundaries, drop bad / overlapping clips
# --------------------------------------------------------------------------- #
def snap_picks(picks: list[ClipPick], segments: list[dict], duration: float, args) -> list[dict]:
    out, last_end = [], -1.0
    for p in picks:
        try:
            s, e = ts_to_seconds(p.start), ts_to_seconds(p.end)
        except ValueError:
            log(f"  Skipping clip with bad timestamps: {p.start} - {p.end}")
            continue
        if segments:
            # Start at the beginning of the segment nearest the suggested start...
            s = min((seg["start"] for seg in segments), key=lambda t: abs(t - s))
            # ...end at the segment end nearest the suggested end, within the max length.
            ends = [seg["end"] for seg in segments if s + 3 < seg["end"] <= s + args.max_len + 2]
            if ends:
                e = min(ends, key=lambda t: abs(t - e))
        s, e = max(0.0, s), min(duration, e)
        if e - s > args.max_len + 2:
            e = s + args.max_len
        if e - s < max(5, args.min_len * 0.5) or s < last_end:
            log(f"  Skipping '{p.title}' ({p.start}-{p.end}): too short or overlapping")
            continue
        text = " ".join(seg["text"] for seg in segments if seg["start"] >= s - 0.5 and seg["end"] <= e + 0.5)
        out.append({**p.model_dump(), "start_sec": round(s, 2), "end_sec": round(e, 2), "transcript": text})
        last_end = e
    return out


# --------------------------------------------------------------------------- #
# Cutting with ffmpeg
# --------------------------------------------------------------------------- #
def video_filter(fmt: str, w: int, h: int) -> str | None:
    if fmt == "original":
        return None
    if fmt == "blur" or w / h <= 9 / 16:
        return ("split[a][b];"
                "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bg];"
                "[b]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2")
    return "crop=trunc(ih*9/16/2)*2:ih,scale=1080:1920"


def cut_clip(src: Path, dst: Path, start: float, end: float, fmt: str, w: int, h: int) -> None:
    args = ["-ss", f"{start:.2f}", "-i", str(src), "-t", f"{end - start:.2f}"]
    vf = video_filter(fmt, w, h)
    if vf:
        args += ["-filter_complex" if ";" in vf else "-vf", vf]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)]
    ffmpeg(*args)


# --------------------------------------------------------------------------- #
# Main pipeline
# --------------------------------------------------------------------------- #
def check_topic(client, videos: list[dict], topic: str) -> list[tuple[dict, str]]:
    """Ask the LLM which videos are about `topic`. Returns [(video, reason), ...]."""
    listing = "\n\n".join(
        f"VIDEO {i}\nTitle: {v['title']}\nDescription: {v['description'][:1200] or '(none)'}"
        for i, v in enumerate(videos, 1))
    prompt = f"""Decide which of these YouTube videos are about the topic: "{topic}".

Judge by meaning, not exact words: a video counts if a meaningful part of it is about the
topic or something closely related (e.g. "my morning routine" counts for "productivity").
A passing mention, sponsor segment or link in the description does NOT count.

Respond with JSON exactly in this shape (one entry per video):
{{"results": [{{"video_number": 1, "relevant": true, "reason": "one short sentence"}}]}}

{listing}"""
    res, _ = ask_llm(client, JSON_ONLY, prompt, TopicMatches, temperature=0.1)
    by_num = {r.video_number: r for r in res.results}
    return [(v, by_num[i].reason) for i, v in enumerate(videos, 1)
            if i in by_num and by_num[i].relevant]


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit("Cancelled.")


def fmt_count(n) -> str:
    if not n:
        return "? subscribers"
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= div:
            return f"{n / div:.1f}".rstrip("0").rstrip(".") + f"{suf} subscribers"
    return f"{n} subscribers"


def fmt_date(d: str | None) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if d and len(d) == 8 else "unknown date"


def choose_channel(name: str) -> dict | None:
    """Resolve a YouTuber name / @handle / channel URL to a channel, asking the user to confirm."""
    import youtube_search as yts

    try:
        direct = yts.channel_from_input(name)
    except Exception as e:  # noqa: BLE001
        print(f"Could not open that channel ({e}).")
        return None
    if direct:
        print(f"Channel: {direct['name']} ({direct['handle']}, {fmt_count(direct['subscribers'])})")
        return direct

    log(f'Searching YouTube for "{name}"...')
    channels = yts.find_channels(name)
    if not channels:
        print(f'No channels found for "{name}".')
        return None
    print("\nChannels found:")
    for i, c in enumerate(channels, 1):
        print(f"  [{i}] {c['name']} ({c['handle']}, {fmt_count(c['subscribers'])})")
    while True:
        pick = ask(f"Which channel? (1-{len(channels)}, Enter = 1, n = none of these): ").lower()
        if pick in ("", "1"):
            return channels[0]
        if pick == "n":
            return None
        if pick.isdigit() and 1 <= int(pick) <= len(channels):
            return channels[int(pick) - 1]


def search_for_video(args, client) -> str:
    """Interactive: YouTuber + topic -> latest videos -> topic check -> user picks one. Returns URL."""
    import youtube_search as yts

    youtuber = args.youtuber or ask("YouTuber name (or @handle): ")
    topic = args.topic or ask("Video topic: ")
    channel, start, cache = None, 1, {}

    while True:
        while channel is None:
            if not youtuber:
                youtuber = ask("YouTuber name (or @handle): ")
                continue
            channel = choose_channel(youtuber)
            if channel is None:
                youtuber = ""
            else:
                start, cache = 1, {}

        end = start + args.latest - 1
        if (start, end) not in cache:
            log(f"Fetching videos {start}-{end} from {channel['name']}...")
            cache[(start, end)] = yts.latest_videos(channel, start, args.latest)
        videos = cache[(start, end)]
        where = f"latest {args.latest} videos" if start == 1 else f"older videos {start}-{end}"

        if not videos:
            print(f"\n{channel['name']} has no more videos.")
            matches = []
        else:
            log(f'Checking which of the {len(videos)} videos are about "{topic}"...')
            matches = check_topic(client, videos, topic)

        if matches:
            print(f'\nFound {len(matches)} video(s) about "{topic}" in the {where} '
                  f"of {channel['name']}:\n")
            for i, (v, reason) in enumerate(matches, 1):
                dur = seconds_to_ts(v["duration"]) if v["duration"] else "?"
                # Skip sponsor / link lines so the preview shows what the video is about.
                text = " ".join(ln for ln in v["description"].splitlines() if "http" not in ln)
                text = " ".join(text.split())
                desc = (text[:220] + ("..." if len(text) > 220 else "")) or "(no description)"
                print(f"  [{i}] {v['title']}")
                print(f"      {fmt_date(v['upload_date'])} | {dur}")
                print(f"      {desc}")
                print(f"      Why it matches: {reason}\n")
            prompt = (f"Choose a video (1-{len(matches)}), or  o = older videos | "
                      f"t = change topic | y = switch YouTuber | q = quit: ")
        else:
            if videos:
                print(f'\nNo videos found about "{topic}" in the {where} of {channel["name"]}.')
            print("\nWhat would you like to do?")
            print("  [y] Switch YouTuber")
            print("  [t] Change topic")
            if videos:
                print(f"  [o] Inspect older videos ({end + 1}-{end + args.latest})")
            print("  [q] Quit")
            prompt = "Choice: "

        while True:
            choice = ask(prompt).lower()
            if matches and choice.isdigit() and 1 <= int(choice) <= len(matches):
                video = matches[int(choice) - 1][0]
                print(f"\nSelected: {video['title']}\n")
                return video["url"]
            if choice == "o" and videos:
                start = end + 1
                break
            if choice == "t":
                topic = ask("New topic: ") or topic
                start = 1
                break
            if choice == "y":
                youtuber, channel = ask("YouTuber name (or @handle): "), None
                break
            if choice == "q":
                sys.exit("Bye.")


def run(args, client: OpenAI | None = None) -> None:
    client = client or llm_client()
    video, meta = get_video(args.source)
    duration, w, h = probe(video)
    log(f"Video: {meta['title']} ({seconds_to_ts(duration)}, {w}x{h})")

    slug = slugify(meta["title"])
    work = WORK / slug
    work.mkdir(parents=True, exist_ok=True)

    # --- Transcribe (cached) ----------------------------------------------
    tr_file = work / "transcript.json"
    if tr_file.exists():
        segments = json.loads(tr_file.read_text(encoding="utf-8"))
        log(f"Reusing saved transcript ({len(segments)} segments)")
    else:
        log(f"Transcribing with {'Groq Whisper' if TRANSCRIBE == 'groq' else 'local Whisper (this can take a while on CPU)'}...")
        segments = (transcribe_groq(video, work, duration) if TRANSCRIBE == "groq"
                    else transcribe_local(video, duration))
        if not segments:
            sys.exit("Whisper found no speech in this video.")
        tr_file.write_text(json.dumps(segments, indent=1, ensure_ascii=False), encoding="utf-8")

    # --- Pick clips (cached) ----------------------------------------------
    picks_file = work / "clip_picks.json"
    if picks_file.exists() and not args.fresh:
        picks = json.loads(picks_file.read_text(encoding="utf-8"))
        log(f"Reusing saved clip picks from {picks_file.relative_to(ROOT)} (use --fresh to redo)")
    else:
        log("Asking the LLM to pick clips from the transcript...")
        raw = find_clips(client, transcript_for_llm(segments), meta, duration, args)
        picks = snap_picks(raw, segments, duration, args)
        picks_file.write_text(json.dumps(picks, indent=2, ensure_ascii=False), encoding="utf-8")
    if not picks:
        sys.exit("No usable clips were returned. Try again with --fresh or another model.")
    log(f"{len(picks)} clips selected:")
    for i, p in enumerate(picks, 1):
        log(f"  {i}. {seconds_to_ts(p['start_sec'])}-{seconds_to_ts(p['end_sec'])}  {p['title']}")

    # --- Captions for all clips in one request ----------------------------
    log("Writing captions, titles and hashtags...")
    metas = describe_clips(client, picks, meta)

    # --- Cut and save -----------------------------------------------------
    insta_out, yt_out = INSTA_DIR / slug, YT_DIR / slug
    insta_out.mkdir(parents=True, exist_ok=True)
    yt_out.mkdir(parents=True, exist_ok=True)

    for i, pick in enumerate(picks, 1):
        cm = metas.get(i)
        if cm is None:
            log(f"[{i}/{len(picks)}] No captions returned for this clip; skipping")
            continue
        name = f"clip_{i:02d}_{slugify(cm.name, 40)}"
        tmp_clip = work / f"{name}.mp4"
        log(f"[{i}/{len(picks)}] Cutting {seconds_to_ts(pick['start_sec'])}-{seconds_to_ts(pick['end_sec'])} -> {name}")
        cut_clip(video, tmp_clip, pick["start_sec"], pick["end_sec"], args.format, w, h)

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
            "format": args.format,
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

    log("Done!")
    log(f"  Instagram clips: {insta_out}")
    log(f"  YouTube clips:   {yt_out}")


def list_models() -> None:
    client = llm_client()
    models = client.models.list().data
    is_openrouter = "openrouter.ai" in LLM_BASE_URL
    rows = []
    for m in models:
        extra = m.model_extra or {}
        if is_openrouter:
            pricing = extra.get("pricing") or {}
            if not (m.id.endswith(":free") or (pricing.get("prompt") == "0" and pricing.get("completion") == "0")):
                continue
            # Skip models that don't output text (music / image generators).
            outputs = (extra.get("architecture") or {}).get("output_modalities") or ["text"]
            if "text" not in outputs:
                continue
        rows.append((m.id, extra.get("context_length") or extra.get("context_window") or ""))
    rows.sort(key=lambda r: -(r[1] or 0) if isinstance(r[1], int) else 0)
    print(f"{'model':60} context")
    for mid, ctx in rows:
        print(f"{mid:60} {ctx}")
    if is_openrouter:
        print("\n(Showing only free OpenRouter models.)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract short clips from a long video with free models.")
    ap.add_argument("source", nargs="?",
                    help="YouTube URL or local video file. Leave out to search by YouTuber + topic.")
    ap.add_argument("--youtuber", help="Search mode: YouTuber name, @handle or channel URL")
    ap.add_argument("--topic", help="Search mode: topic the video should be about")
    ap.add_argument("--latest", type=int, default=5, help="Search mode: how many recent videos to check")
    ap.add_argument("--min-clips", type=int, default=5)
    ap.add_argument("--max-clips", type=int, default=7)
    ap.add_argument("--min-len", type=int, default=20, help="Minimum clip length in seconds")
    ap.add_argument("--max-len", type=int, default=60, help="Maximum clip length in seconds")
    ap.add_argument("--format", choices=["crop", "blur", "original"], default="crop",
                    help="crop = centre-crop to 9:16, blur = full frame on blurred 9:16 background, "
                         "original = keep source aspect ratio")
    ap.add_argument("--fresh", action="store_true", help="Ignore saved clip picks and ask the LLM again")
    ap.add_argument("--list-models", action="store_true", help="List models available at LLM_BASE_URL")
    args = ap.parse_args()

    if args.list_models:
        return list_models()
    client = llm_client()
    if not args.source:
        args.source = search_for_video(args, client)
    run(args, client)


if __name__ == "__main__":
    main()
