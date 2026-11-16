from __future__ import annotations

import re


def slugify(text: str, max_len: int = 50) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:max_len].strip("_") or "video"


def ts_to_seconds(ts) -> float:
    """'HH:MM:SS', 'MM:SS' or a number -> seconds."""
    if isinstance(ts, (int, float)):
        return float(ts)
    secs = 0.0
    for p in str(ts).strip().split(":"):
        secs = secs * 60 + float(p)
    return secs


def seconds_to_ts(secs: float) -> str:
    secs = int(round(secs))
    return f"{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"
