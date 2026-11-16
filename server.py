"""
Clipper web server: a FastAPI app around the clipper.py pipeline.

  .venv\\Scripts\\python server.py          ->  http://127.0.0.1:8000

Serves the API under /api, the generated clips under /media, and the built
frontend (frontend/out) at /.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import clipper
import youtube_search as yts

ROOT = clipper.ROOT
UPLOADS = clipper.DOWNLOADS / "uploads"
FRONTEND = ROOT / "frontend" / "out"
STAGES = [
    ("download", "Download"),
    ("transcribe", "Transcribe"),
    ("pick", "Pick clips"),
    ("captions", "Write captions"),
    ("cut", "Cut & save"),
]

app = FastAPI(title="Clipper")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@app.get("/api/config")
def config():
    return {
        "llm_models": clipper.LLM_MODELS,
        "llm_base_url": clipper.LLM_BASE_URL,
        "llm_key_set": bool(clipper.LLM_API_KEY),
        "transcribe": clipper.TRANSCRIBE,
        "groq_key_set": bool(clipper.GROQ_API_KEY),
    }


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
class ChannelQuery(BaseModel):
    query: str


@app.post("/api/channels")
def channels(q: ChannelQuery):
    text = q.query.strip()
    if not text:
        raise HTTPException(400, "Enter a YouTuber name or @handle")
    try:
        direct = yts.channel_from_input(text)
        return {"channels": [direct] if direct else yts.find_channels(text)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"YouTube lookup failed: {e}") from e


class VideoQuery(BaseModel):
    channel: dict
    topic: str
    start: int = Field(1, ge=1)
    count: int = Field(5, ge=1, le=25)


_video_cache: dict[tuple, list[dict]] = {}


@app.post("/api/videos")
def videos(q: VideoQuery):
    if not q.topic.strip():
        raise HTTPException(400, "Enter a topic")
    key = (q.channel.get("id"), q.start, q.count)
    try:
        if key not in _video_cache:
            _video_cache[key] = yts.latest_videos(q.channel, q.start, q.count)
        vids = _video_cache[key]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not load videos: {e}") from e
    if not vids:
        return {"videos": [], "start": q.start, "count": q.count, "end_of_channel": True}
    try:
        matches = {v["id"]: reason for v, reason in
                   clipper.check_topic(clipper.llm_client(), vids, q.topic.strip())}
    except SystemExit as e:
        raise HTTPException(400, str(e.code)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Topic check failed: {e}") from e
    return {
        "videos": [{**v, "matched": v["id"] in matches, "reason": matches.get(v["id"], "")}
                   for v in vids],
        "start": q.start,
        "count": q.count,
        "end_of_channel": False,
    }


# --------------------------------------------------------------------------- #
# Upload a local file
# --------------------------------------------------------------------------- #
@app.post("/api/upload")
def upload(file: UploadFile):
    UPLOADS.mkdir(parents=True, exist_ok=True)
    name = Path(file.filename or "video.mp4").name
    dest = UPLOADS / name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"path": str(dest)}


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
class JobRequest(BaseModel):
    source: str
    min_clips: int = Field(5, ge=1, le=20)
    max_clips: int = Field(7, ge=1, le=20)
    min_len: int = Field(20, ge=5, le=600)
    max_len: int = Field(60, ge=5, le=600)
    format: str = Field("crop", pattern="^(crop|blur|original)$")
    fresh: bool = False


class Job:
    def __init__(self, req: JobRequest):
        self.id = uuid.uuid4().hex[:12]
        self.req = req
        self.status = "running"  # running | done | error
        self.error: str | None = None
        self.result: dict | None = None
        self.started = time.time()
        self.finished: float | None = None
        self.logs: list[str] = []
        self.stages = {k: {"key": k, "label": label, "status": "pending",
                           "progress": 0.0, "detail": None, "indeterminate": False}
                       for k, label in STAGES}
        self._current: str | None = None

    # reporter interface used by clipper.py
    def log(self, msg: str) -> None:
        self.logs.append(f"{time.strftime('%H:%M:%S')}  {msg}")
        del self.logs[:-500]

    def progress(self, stage: str, fraction: float | None, detail: str | None) -> None:
        st = self.stages.get(stage)
        if st is None:
            return
        # Starting a stage completes every earlier stage (cached steps are skipped quickly).
        keys = [k for k, _ in STAGES]
        for k in keys[: keys.index(stage)]:
            if self.stages[k]["status"] != "done":
                self.stages[k].update(status="done", progress=1.0)
        self._current = stage
        st["status"] = "done" if fraction is not None and fraction >= 1 else "running"
        st["progress"] = st["progress"] if fraction is None else max(0.0, min(1.0, fraction))
        st["indeterminate"] = fraction is None
        if detail is not None:
            st["detail"] = detail

    def fail(self, msg: str) -> None:
        self.status, self.error = "error", msg
        if self._current:
            self.stages[self._current]["status"] = "error"
        self.log(f"ERROR: {msg}")

    def to_dict(self) -> dict:
        stages = list(self.stages.values())
        overall = sum(s["progress"] if s["status"] != "done" else 1.0 for s in stages) / len(stages)
        return {
            "id": self.id,
            "status": self.status,
            "error": self.error,
            "result": self.result,
            "request": self.req.model_dump(),
            "started": self.started,
            "finished": self.finished,
            "overall": 1.0 if self.status == "done" else overall,
            "stages": stages,
            "logs": self.logs[-200:],
        }


jobs: dict[str, Job] = {}
_current_job: Job | None = None
_lock = threading.Lock()


def _run_job(job: Job) -> None:
    clipper.REPORTER.set(job)
    r = job.req
    args = SimpleNamespace(source=r.source, min_clips=r.min_clips, max_clips=max(r.min_clips, r.max_clips),
                           min_len=r.min_len, max_len=max(r.min_len, r.max_len),
                           format=r.format, fresh=r.fresh)
    try:
        job.result = clipper.run(args)
        job.status = "done"
    except SystemExit as e:  # clipper uses sys.exit("message") for user-facing errors
        job.fail(str(e.code))
    except Exception as e:  # noqa: BLE001
        job.fail(f"{type(e).__name__}: {e}")
    finally:
        job.finished = time.time()


@app.post("/api/jobs")
def start_job(req: JobRequest):
    global _current_job
    with _lock:
        if _current_job and _current_job.status == "running":
            raise HTTPException(409, "A job is already running. Wait for it to finish.")
        job = Job(req)
        jobs[job.id] = job
        _current_job = job
    threading.Thread(target=_run_job, args=(job,), daemon=True).start()
    return job.to_dict()


@app.get("/api/jobs/current")
def current_job():
    return _current_job.to_dict() if _current_job else None


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.to_dict()


# --------------------------------------------------------------------------- #
# Library (reads the clips saved on disk)
# --------------------------------------------------------------------------- #
def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


@app.get("/api/library")
def library():
    slugs = {p.name for d in (clipper.INSTA_DIR, clipper.YT_DIR) if d.exists()
             for p in d.iterdir() if p.is_dir()}
    items = []
    for slug in slugs:
        jsons = sorted((clipper.INSTA_DIR / slug).glob("*.json")) or sorted((clipper.YT_DIR / slug).glob("*.json"))
        if not jsons:
            continue
        first = _read_json(jsons[0])
        src = first.get("source_video") or {}
        mtime = max(p.stat().st_mtime for p in jsons)
        items.append({
            "slug": slug,
            "title": src.get("title") or slug,
            "channel": src.get("channel"),
            "url": src.get("url"),
            "clip_count": len(jsons),
            "updated": mtime,
            "thumbnail": f"https://i.ytimg.com/vi/{src['id']}/mqdefault.jpg"
                         if src.get("url") and src.get("id") else None,
        })
    items.sort(key=lambda x: -x["updated"])
    return {"items": items}


@app.get("/api/library/{slug}")
def library_item(slug: str):
    insta_dir, yt_dir = clipper.INSTA_DIR / slug, clipper.YT_DIR / slug
    if not insta_dir.resolve().is_relative_to(clipper.INSTA_DIR.resolve()):
        raise HTTPException(400, "Bad name")
    names = sorted({p.stem for d in (insta_dir, yt_dir) if d.exists() for p in d.glob("*.json")})
    if not names:
        raise HTTPException(404, "No clips found")
    clips = []
    for name in names:
        ig = _read_json(insta_dir / f"{name}.json")
        yt = _read_json(yt_dir / f"{name}.json")
        base = ig or yt
        clips.append({
            "name": name,
            "clip_number": base.get("clip_number"),
            "working_title": base.get("working_title"),
            "summary": base.get("summary"),
            "hook": base.get("hook"),
            "reason": base.get("reason"),
            "transcript": base.get("transcript"),
            "start": base.get("start"),
            "end": base.get("end"),
            "duration_sec": base.get("duration_sec"),
            "format": base.get("format"),
            "created_at": base.get("created_at"),
            "source_video": base.get("source_video"),
            "instagram": {
                "caption": ig.get("caption"), "hashtags": ig.get("hashtags") or [],
                "full_caption": ig.get("full_caption"),
                "video": f"/media/insta_vid/{slug}/{name}.mp4" if (insta_dir / f"{name}.mp4").exists() else None,
                "json": f"/media/insta_vid/{slug}/{name}.json" if ig else None,
            } if ig else None,
            "youtube": {
                "title": yt.get("title"), "description": yt.get("description"),
                "tags": yt.get("tags") or [], "hashtags": yt.get("hashtags") or [],
                "full_description": yt.get("full_description"),
                "video": f"/media/yt_vids/{slug}/{name}.mp4" if (yt_dir / f"{name}.mp4").exists() else None,
                "json": f"/media/yt_vids/{slug}/{name}.json" if yt else None,
            } if yt else None,
        })
    src = clips[0].get("source_video") or {}
    return {"slug": slug, "title": src.get("title") or slug, "source_video": src, "clips": clips}


# --------------------------------------------------------------------------- #
# Static files
# --------------------------------------------------------------------------- #
for _d in (clipper.INSTA_DIR, clipper.YT_DIR):
    _d.mkdir(exist_ok=True)
app.mount("/media/insta_vid", StaticFiles(directory=clipper.INSTA_DIR), name="insta")
app.mount("/media/yt_vids", StaticFiles(directory=clipper.YT_DIR), name="yt")
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="ui")


if __name__ == "__main__":
    import uvicorn

    print("Clipper UI: http://127.0.0.1:8000" if FRONTEND.exists()
          else "API running. Build the UI with `npm run build` in frontend/, or run `npm run dev` there.")
    uvicorn.run(app, host="127.0.0.1", port=8000)
