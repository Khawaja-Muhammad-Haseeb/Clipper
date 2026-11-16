"""Logging and progress reporting.

Everything prints to the console. When a reporter is set for the current thread
(the API does this for each job), log lines and stage progress go to it as well.

A reporter needs:  .log(msg)  and  .progress(stage, fraction_or_None, detail_or_None)
Stages, in order:  download, transcribe, pick, captions, cut
"""

from __future__ import annotations

import contextvars
from datetime import datetime
from typing import Protocol


class Reporter(Protocol):
    def log(self, msg: str) -> None: ...
    def progress(self, stage: str, fraction: float | None, detail: str | None) -> None: ...


STAGES: list[tuple[str, str]] = [
    ("download", "Download"),
    ("transcribe", "Transcribe"),
    ("pick", "Pick clips"),
    ("captions", "Write captions"),
    ("cut", "Cut & save"),
]

REPORTER: contextvars.ContextVar[Reporter | None] = contextvars.ContextVar("reporter", default=None)


def log(msg: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)
    if (r := REPORTER.get()) is not None:
        r.log(msg)


def progress(stage: str, fraction: float | None, detail: str | None = None) -> None:
    """fraction: 0..1, or None when the stage is running but can't measure progress."""
    if (r := REPORTER.get()) is not None:
        r.progress(stage, fraction, detail)
