"""Request bodies."""

from __future__ import annotations

from pydantic import BaseModel, Field

from clipper.schemas import ClipFormat, ClipOptions


class ChannelQuery(BaseModel):
    query: str


class VideoQuery(BaseModel):
    channel: dict
    topic: str
    start: int = Field(1, ge=1)
    count: int = Field(5, ge=1, le=25)


class JobRequest(BaseModel):
    source: str
    min_clips: int = Field(5, ge=1, le=20)
    max_clips: int = Field(7, ge=1, le=20)
    min_len: int = Field(20, ge=5, le=600)
    max_len: int = Field(60, ge=5, le=600)
    format: ClipFormat = "crop"
    fresh: bool = False

    def options(self) -> ClipOptions:
        return ClipOptions(min_clips=self.min_clips, max_clips=self.max_clips, min_len=self.min_len,
                           max_len=self.max_len, format=self.format, fresh=self.fresh)
