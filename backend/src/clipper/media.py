"""ffmpeg helpers (uses the ffmpeg binary bundled with imageio-ffmpeg)."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg

from clipper.errors import ClipperError
from clipper.schemas import ClipFormat

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def ffmpeg_dir() -> str:
    """A folder containing the bundled binary under the standard name (ffmpeg / ffmpeg.exe).
    yt-dlp needs this for partial (section) downloads."""
    exe = Path(FFMPEG)
    named = exe.with_name("ffmpeg.exe" if exe.suffix == ".exe" else "ffmpeg")
    if not named.exists():
        try:
            os.link(exe, named)            # hard link: no extra disk space
        except OSError:
            shutil.copy2(exe, named)
    # yt-dlp's section downloader looks for ffmpeg on PATH, not in ffmpeg_location.
    folder = str(named.parent)
    if folder not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
    return folder


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


# Output frame: 1080x1920 (9:16). Blurs run on a small copy and are scaled back up:
# visually the same, several times faster than blurring at full resolution.
W, H = 1080, 1920
HALF = H // 2
FIT = "force_original_aspect_ratio=decrease:force_divisible_by=2"
FILL = "force_original_aspect_ratio=increase"


def _blurred_fill(w: int, h: int, strength: int = 6) -> str:
    """Scale + crop to fill w x h, then blur (cheaply, at 1/4 size)."""
    return (f"scale={w}:{h}:{FILL},crop={w}:{h},scale={w // 4}:{h // 4},"
            f"boxblur={strength}:2,scale={w}:{h},setsar=1")


def video_filter(fmt: ClipFormat, w: int, h: int) -> str | None:
    """ffmpeg filter graph for a format. Input 0 = clip, input 1 = background video.
    Graphs end in the label [v]."""
    if fmt == "original":
        return None
    if fmt == "crop" and w / h > 9 / 16:
        # Centre-crop to 9:16 (loses the sides of a 16:9 video).
        return f"[0:v]crop=trunc(ih*9/16/2)*2:ih,scale={W}:{H},setsar=1[v]"
    if fmt in ("crop", "blur"):
        # Whole frame, full width, over a blurred copy of itself.
        return (f"[0:v]split[a][b];[a]{_blurred_fill(W, H, 8)}[bg];"
                f"[b]scale={W}:{H}:{FIT},setsar=1[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v]")
    if fmt == "background":
        # Layout A: whole clip, full width, centred over a blurred background video.
        return (f"[1:v]fps=30,{_blurred_fill(W, H, 4)}[bg];"
                f"[0:v]fps=30,scale={W}:{H}:{FIT},setsar=1[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v]")
    if fmt == "split":
        # Layout B: top half = whole clip (gaps filled with its own blur),
        # bottom half = background video, sharp.
        return (f"[0:v]fps=30,split[a][b];[a]{_blurred_fill(W, HALF, 8)}[tbg];"
                f"[b]scale={W}:{HALF}:{FIT},setsar=1[tfg];"
                f"[tbg][tfg]overlay=(W-w)/2:(H-h)/2[top];"
                f"[1:v]fps=30,scale={W}:{HALF}:{FILL},crop={W}:{HALF},setsar=1[bot];"
                f"[top][bot]vstack=inputs=2[v]")
    raise ClipperError(f"Unknown format: {fmt}")


def needs_background(fmt: ClipFormat) -> bool:
    return fmt in ("background", "split")


def cut_clip(src: Path, dst: Path, start: float, end: float, fmt: ClipFormat, w: int, h: int,
             background: tuple[Path, float] | None = None) -> None:
    """Cut [start, end] from src into dst in the given format.
    background = (video, offset): a slice of the same length is taken from the background,
    looping it if it is shorter than the clip. Its audio is ignored."""
    duration = end - start
    args = ["-ss", f"{start:.2f}", "-i", str(src)]
    if needs_background(fmt):
        if background is None:
            raise ClipperError(f"Format '{fmt}' needs a background video")
        bg, offset = background
        args += ["-stream_loop", "-1", "-ss", f"{offset:.2f}", "-i", str(bg)]
    args += ["-t", f"{duration:.2f}"]
    graph = video_filter(fmt, w, h)
    if graph:
        args += ["-filter_complex", graph, "-map", "[v]", "-map", "0:a?"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)]
    ffmpeg(*args)


# Put ffmpeg on PATH at import: yt-dlp checks for it once and caches the answer,
# so this must happen before any yt-dlp call.
ffmpeg_dir()
