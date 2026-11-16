"""Speech-to-text with Whisper: Groq's free API or faster-whisper locally."""

from __future__ import annotations

from pathlib import Path

from openai import OpenAI

from clipper import config
from clipper.errors import ClipperError
from clipper.media import extract_audio, read_pcm
from clipper.reporting import log, progress
from clipper.utils import seconds_to_ts

Segment = dict  # {"start": float, "end": float, "text": str}

GROQ_CHUNK_SEC = 1800  # 30 min of 16 kHz mono 48 kbps mp3 ~ 11 MB, under Groq's 25 MB limit


def transcribe(video: Path, work: Path, duration: float) -> list[Segment]:
    if config.TRANSCRIBE == "groq":
        log("Transcribing with Groq Whisper...")
        return _groq(video, work, duration)
    log("Transcribing with local Whisper (this can take a while on CPU)...")
    return _local(video, duration)


def _groq(video: Path, work: Path, duration: float) -> list[Segment]:
    if not config.GROQ_API_KEY:
        raise ClipperError("TRANSCRIBE=groq but GROQ_API_KEY is not set in backend/.env")
    client = OpenAI(api_key=config.GROQ_API_KEY, base_url=config.GROQ_BASE_URL, max_retries=3)
    segments: list[Segment] = []
    offset = 0.0
    while offset < duration:
        audio = work / f"audio_{int(offset)}.mp3"
        extract_audio(video, audio, offset, GROQ_CHUNK_SEC)
        end = min(duration, offset + GROQ_CHUNK_SEC)
        log(f"  Transcribing {seconds_to_ts(offset)} - {seconds_to_ts(end)} (Groq)")
        progress("transcribe", offset / duration, f"{seconds_to_ts(offset)} / {seconds_to_ts(duration)}")
        try:
            with open(audio, "rb") as f:
                resp = client.audio.transcriptions.create(
                    file=(audio.name, f.read()), model=config.GROQ_WHISPER_MODEL,
                    response_format="verbose_json", timestamp_granularities=["segment"])
        finally:
            audio.unlink(missing_ok=True)
        data = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        for s in data.get("segments") or []:
            segments.append({"start": round(s["start"] + offset, 2),
                             "end": round(s["end"] + offset, 2),
                             "text": s["text"].strip()})
        offset += GROQ_CHUNK_SEC
    return segments


def _local(video: Path, duration: float) -> list[Segment]:
    import numpy as np
    from faster_whisper import WhisperModel

    log(f"  Loading local Whisper model '{config.LOCAL_WHISPER_MODEL}' (first run downloads it)")
    model = WhisperModel(config.LOCAL_WHISPER_MODEL, device="cpu", compute_type="int8")
    # Decode with our bundled ffmpeg instead of PyAV (avoids version conflicts).
    audio = np.frombuffer(read_pcm(video), np.int16).astype(np.float32) / 32768.0
    seg_iter, _ = model.transcribe(audio, vad_filter=True, beam_size=1)
    segments: list[Segment] = []
    last_report = 0.0
    for s in seg_iter:
        segments.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()})
        progress("transcribe", min(0.99, s.end / duration), f"{seconds_to_ts(s.end)} / {seconds_to_ts(duration)}")
        if s.end - last_report > 120:
            log(f"  Transcribed {seconds_to_ts(s.end)} / {seconds_to_ts(duration)}")
            last_report = s.end
    return segments


def format_for_llm(segments: list[Segment], block: float = 10.0) -> str:
    """Merge segments into ~10 s lines like '[00:12:30] text' to save tokens."""
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
