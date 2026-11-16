"""
One-time migration: data/insta_vid + data/yt_vids  ->  data/clips

For every clip, writes one combined JSON (Instagram + YouTube metadata) and keeps a
single copy of the video. The duplicate yt_vids copy is deleted.

  .venv\\Scripts\\python backend\\scripts\\migrate_single_folder.py                    # dry run
  .venv\\Scripts\\python backend\\scripts\\migrate_single_folder.py --apply
  .venv\\Scripts\\python backend\\scripts\\migrate_single_folder.py --apply --delete-sources

--delete-sources also deletes downloaded source videos in data/downloads whose clips
exist (transcripts in data/work are kept, so they can be re-clipped later).
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from clipper import config

OLD_INSTA = config.DATA_DIR / "insta_vid"
OLD_YT = config.DATA_DIR / "yt_vids"
COMMON = ("name", "clip_number", "working_title", "summary", "hook", "reason", "transcript",
          "start", "end", "duration_sec", "format", "source_video", "created_at")


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually move files (default: dry run)")
    ap.add_argument("--delete-sources", action="store_true", help="Also delete source videos in data/downloads")
    args = ap.parse_args()

    slugs = sorted({p.name for root in (OLD_INSTA, OLD_YT) if root.exists() for p in root.iterdir() if p.is_dir()})
    freed = 0
    source_ids = set()
    for slug in slugs:
        ig_dir, yt_dir, out = OLD_INSTA / slug, OLD_YT / slug, config.CLIPS_DIR / slug
        names = sorted({p.stem for d in (ig_dir, yt_dir) if d.exists() for p in d.glob("*.json")})
        print(f"{slug}: {len(names)} clips")
        for name in names:
            ig, yt = read(ig_dir / f"{name}.json"), read(yt_dir / f"{name}.json")
            base = ig or yt
            if (base.get("source_video") or {}).get("url"):
                source_ids.add(base["source_video"].get("id"))
            merged = {k: base.get(k) for k in COMMON}
            merged["name"] = name
            merged["video_file"] = f"{name}.mp4"
            merged["instagram"] = {k: ig.get(k) for k in ("caption", "hashtags", "full_caption")} | {"uploaded": bool(ig.get("uploaded"))} if ig else None
            merged["youtube"] = {k: yt.get(k) for k in ("title", "description", "tags", "hashtags", "full_description")} | {"uploaded": bool(yt.get("uploaded"))} if yt else None
            video = next((p for p in (ig_dir / f"{name}.mp4", yt_dir / f"{name}.mp4") if p.exists()), None)
            dup = yt_dir / f"{name}.mp4"
            if video and video != dup and dup.exists():
                freed += dup.stat().st_size
            if args.apply:
                out.mkdir(parents=True, exist_ok=True)
                if video:
                    shutil.move(str(video), out / f"{name}.mp4")
                (out / f"{name}.json").write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")

    sources = [config.DOWNLOADS_DIR / f"{i}.mp4" for i in source_ids if (config.DOWNLOADS_DIR / f"{i}.mp4").exists()]
    if args.delete_sources:
        freed += sum(p.stat().st_size for p in sources)

    if args.apply:
        for root in (OLD_INSTA, OLD_YT):
            if root.exists():
                shutil.rmtree(root)
        if args.delete_sources:
            for p in sources:
                p.unlink()
        print(f"\nDone. Freed {freed / 1e6:.0f} MB. Clips are in {config.CLIPS_DIR}")
    else:
        print(f"\nDry run: would free {freed / 1e6:.0f} MB"
              + ("" if args.delete_sources else f" (+{sum(p.stat().st_size for p in sources) / 1e6:.0f} MB with --delete-sources)")
              + ". Re-run with --apply.")


if __name__ == "__main__":
    main()
