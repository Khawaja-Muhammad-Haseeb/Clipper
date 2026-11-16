"""Pipeline options and the JSON shapes the LLM must answer with."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

ClipFormat = Literal["crop", "blur", "original", "background", "split"]


@dataclass
class ClipOptions:
    min_clips: int = 5
    max_clips: int = 7
    min_len: int = 20       # seconds
    max_len: int = 60       # seconds
    format: ClipFormat = "crop"
    fresh: bool = False     # ignore cached clip picks
    keep_source: bool = False  # keep the downloaded / uploaded source video after clipping

    def __post_init__(self) -> None:
        self.max_clips = max(self.min_clips, self.max_clips)
        self.max_len = max(self.min_len, self.max_len)


# ---- LLM responses ----------------------------------------------------------
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
