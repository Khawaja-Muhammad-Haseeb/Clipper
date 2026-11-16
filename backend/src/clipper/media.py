"""ffmpeg helpers (uses the ffmpeg binary bundled with imageio-ffmpeg)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

from clipper.errors import ClipperError
from clipper.schemas import ClipFormat

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def ffmpeg(*args: str) -> None:
    res = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args],
                         capture_output=True, text=True, errors="replace")
    if res.returncode != 0:
        raise ClipperError(f"ffmpeg failed: {res.stderr.strip()}")


def probe(path: Path) -> tuple[float, int, int]:
    """Return (duration_seconds, width, height) by parsing ffmpeg's output."""
    out = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)],
                         capture_output=True, text=True, errors="replace").stderr
    d = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
    v = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", out)
    if not d or not v:
        raise ClipperError(f"Could not read video info from {path}")
    return int(d[1]) * 3600 + int(d[2]) * 60 + float(d[3]), int(v[1]), int(v[2])


def extract_audio(video: Path, dst: Path, start: float, length: float) -> None:
    """16 kHz mono mp3: small enough for transcription APIs."""
    ffmpeg("-ss", str(start), "-t", str(length), "-i", str(video),
           "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(dst))


def read_pcm(video: Path) -> bytes:
    """Whole audio track as 16 kHz mono signed 16-bit PCM."""
    return subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(video),
                           "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                          capture_output=True, check=True).stdout


def video_filter(fmt: ClipFormat, w: int, h: int) -> str | None:
    if fmt == "original":
        return None
    if fmt == "blur" or w / h <= 9 / 16:
        # Whole frame visible, centred over a blurred, zoomed copy of itself.
        return ("split[a][b];"
                "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bg];"
                "[b]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2")
    # Centre-crop to 9:16, then scale to 1080x1920.
    return "crop=trunc(ih*9/16/2)*2:ih,scale=1080:1920"


def cut_clip(src: Path, dst: Path, start: float, end: float, fmt: ClipFormat, w: int, h: int) -> None:
    args = ["-ss", f"{start:.2f}", "-i", str(src), "-t", f"{end - start:.2f}"]
    vf = video_filter(fmt, w, h)
    if vf:
        args += ["-filter_complex" if ";" in vf else "-vf", vf]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)]
    ffmpeg(*args)
