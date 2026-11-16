"""Command-line interface.

  clipper "https://www.youtube.com/watch?v=..."      clip a specific video
  clipper path/to/video.mp4                           clip a local file
  clipper --youtuber "Ali Abdaal" --topic money       search mode
  clipper                                             search mode, asks for everything
  clipper --list-models                               free models at LLM_BASE_URL
"""

from __future__ import annotations

import argparse
import sys

from openai import OpenAI

from clipper import analysis, llm, pipeline, youtube
from clipper.errors import ClipperError
from clipper.reporting import log
from clipper.schemas import ClipOptions
from clipper.utils import seconds_to_ts


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit("Cancelled.")


def _subs(n) -> str:
    if not n:
        return "? subscribers"
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= div:
            return f"{n / div:.1f}".rstrip("0").rstrip(".") + f"{suf} subscribers"
    return f"{n} subscribers"


def _date(d: str | None) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:]}" if d and len(d) == 8 else "unknown date"


def choose_channel(name: str) -> dict | None:
    """Resolve a name / @handle / channel URL to a channel, asking the user to confirm."""
    try:
        direct = youtube.channel_from_input(name)
    except Exception as e:  # noqa: BLE001
        print(f"Could not open that channel ({e}).")
        return None
    if direct:
        print(f"Channel: {direct['name']} ({direct['handle']}, {_subs(direct['subscribers'])})")
        return direct

    log(f'Searching YouTube for "{name}"...')
    channels = youtube.find_channels(name)
    if not channels:
        print(f'No channels found for "{name}".')
        return None
    print("\nChannels found:")
    for i, c in enumerate(channels, 1):
        print(f"  [{i}] {c['name']} ({c['handle']}, {_subs(c['subscribers'])})")
    while True:
        pick = ask(f"Which channel? (1-{len(channels)}, Enter = 1, n = none of these): ").lower()
        if pick in ("", "1"):
            return channels[0]
        if pick == "n":
            return None
        if pick.isdigit() and 1 <= int(pick) <= len(channels):
            return channels[int(pick) - 1]


def search_for_video(youtuber: str | None, topic: str | None, per_page: int, client: OpenAI) -> str:
    """Interactive: YouTuber + topic -> latest videos -> topic check -> user picks one. Returns URL."""
    youtuber = youtuber or ask("YouTuber name (or @handle): ")
    topic = topic or ask("Video topic: ")
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

        end = start + per_page - 1
        if (start, end) not in cache:
            log(f"Fetching videos {start}-{end} from {channel['name']}...")
            cache[(start, end)] = youtube.latest_videos(channel, start, per_page)
        videos = cache[(start, end)]
        where = f"latest {per_page} videos" if start == 1 else f"older videos {start}-{end}"

        if not videos:
            print(f"\n{channel['name']} has no more videos.")
            matches = []
        else:
            log(f'Checking which of the {len(videos)} videos are about "{topic}"...')
            matches = analysis.check_topic(client, videos, topic)

        if matches:
            print(f'\nFound {len(matches)} video(s) about "{topic}" in the {where} of {channel["name"]}:\n')
            for i, (v, reason) in enumerate(matches, 1):
                dur = seconds_to_ts(v["duration"]) if v["duration"] else "?"
                # Skip sponsor / link lines so the preview shows what the video is about.
                text = " ".join(" ".join(ln for ln in v["description"].splitlines() if "http" not in ln).split())
                desc = (text[:220] + ("..." if len(text) > 220 else "")) or "(no description)"
                print(f"  [{i}] {v['title']}")
                print(f"      {_date(v['upload_date'])} | {dur}")
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
                print(f"  [o] Inspect older videos ({end + 1}-{end + per_page})")
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


def print_models() -> None:
    rows = llm.list_models()
    print(f"{'model':60} context")
    for mid, ctx in rows:
        print(f"{mid:60} {ctx}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="clipper", description="Extract short clips from a long video with free models.")
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

    try:
        if args.list_models:
            return print_models()
        client = llm.client()
        source = args.source or search_for_video(args.youtuber, args.topic, args.latest, client)
        opts = ClipOptions(min_clips=args.min_clips, max_clips=args.max_clips, min_len=args.min_len,
                           max_len=args.max_len, format=args.format, fresh=args.fresh)
        pipeline.run(source, opts, client)
    except ClipperError as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
