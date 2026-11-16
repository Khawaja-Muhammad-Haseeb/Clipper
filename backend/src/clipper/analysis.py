"""The three LLM tasks: topic check, clip picking, caption writing."""

from __future__ import annotations

from openai import OpenAI

from clipper import llm
from clipper.reporting import log
from clipper.schemas import ClipMeta, ClipMetas, ClipOptions, ClipPick, ClipPicks, TopicMatches
from clipper.utils import seconds_to_ts


def check_topic(client: OpenAI, videos: list[dict], topic: str) -> list[tuple[dict, str]]:
    """Which videos are about `topic`? Returns [(video, reason), ...] for the matches."""
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
    res, _ = llm.ask(client, prompt, TopicMatches, temperature=0.1)
    by_num = {r.video_number: r for r in res.results}
    return [(v, by_num[i].reason) for i, v in enumerate(videos, 1)
            if i in by_num and by_num[i].relevant]


def find_clips(client: OpenAI, transcript: str, meta: dict, duration: float,
               opts: ClipOptions) -> list[ClipPick]:
    prompt = f"""You are an expert short-form video editor who finds viral moments for
Instagram Reels and YouTube Shorts.

Below is the timestamped transcript of a video (total length {seconds_to_ts(duration)}).
Pick the {opts.min_clips}-{opts.max_clips} BEST self-contained moments to turn into short clips.

Video title: {meta.get('title')}
Channel: {meta.get('channel') or 'unknown'}

Rules for each clip:
- Between {opts.min_len} and {opts.max_len} seconds long.
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
    picks, model = llm.ask(client, prompt, ClipPicks, temperature=0.4)
    log(f"  Clips picked by {model}")
    return picks.clips


def describe_clips(client: OpenAI, picks: list[dict], meta: dict) -> dict[int, ClipMeta]:
    """Captions for all clips in one request. Returns {clip_number: ClipMeta}."""
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
    metas, model = llm.ask(client, prompt, ClipMetas, temperature=0.8)
    log(f"  Captions written by {model}")
    return {m.clip_number: m for m in metas.clips}
