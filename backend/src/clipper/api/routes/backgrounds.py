"""Manage background videos: list, download random ones, add from a link or file, delete."""

from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field

from clipper import backgrounds

router = APIRouter(prefix="/backgrounds", tags=["backgrounds"])


class DownloadRequest(BaseModel):
    count: int = Field(12, ge=1, le=30)


class LinkRequest(BaseModel):
    url: str


class _Task:
    """The one background-download task that can run at a time."""

    def __init__(self) -> None:
        self.state = {"running": False, "done": 0, "total": 0, "current": None, "error": None, "added": 0}
        self._lock = threading.Lock()

    def start(self, fn, total: int) -> bool:
        with self._lock:
            if self.state["running"]:
                return False
            self.state = {"running": True, "done": 0, "total": total, "current": None, "error": None, "added": 0}
        threading.Thread(target=self._run, args=(fn,), daemon=True).start()
        return True

    def _run(self, fn) -> None:
        try:
            self.state["added"] = len(fn())
        except Exception as e:  # noqa: BLE001
            self.state["error"] = str(e)
        finally:
            self.state["running"] = False
            self.state["current"] = None

    def on_progress(self, done: int, total: int, current: str) -> None:
        self.state.update(done=done, total=total, current=current)


task = _Task()


@router.get("")
def list_backgrounds():
    return {"items": backgrounds.list_all(), "task": task.state}


@router.get("/status")
def status():
    return task.state


@router.post("/download")
def download_random(req: DownloadRequest):
    if not task.start(lambda: backgrounds.download_random(req.count, task.on_progress), req.count):
        raise HTTPException(409, "A background download is already running")
    return task.state


@router.post("/youtube")
def add_link(req: LinkRequest):
    url = req.url.strip()
    if "://" not in url:
        raise HTTPException(400, "Enter a YouTube link")

    def run():
        task.on_progress(0, 1, url)
        return [backgrounds.add_from_youtube(url)]

    if not task.start(run, 1):
        raise HTTPException(409, "A background download is already running")
    return task.state


@router.post("/upload")
def upload(file: UploadFile):
    name = Path(file.filename or "background.mp4")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name.name
        with path.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        return backgrounds.add_file(path, title=name.stem)


@router.delete("/{bg_id}")
def delete(bg_id: str):
    if not backgrounds.delete(bg_id):
        raise HTTPException(404, "Background not found")
    return {"ok": True}
