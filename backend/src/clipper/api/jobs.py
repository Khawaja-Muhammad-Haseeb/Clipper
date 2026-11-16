"""Background jobs: runs the pipeline in a thread and records its progress."""

from __future__ import annotations

import threading
import time
import uuid

from clipper import pipeline
from clipper.api.schemas import JobRequest
from clipper.errors import ClipperError
from clipper.reporting import REPORTER, STAGES


class Job:
    """Also acts as the pipeline's reporter (see clipper.reporting)."""

    def __init__(self, req: JobRequest):
        self.id = uuid.uuid4().hex[:12]
        self.req = req
        self.status = "running"  # running | done | error
        self.error: str | None = None
        self.result: dict | None = None
        self.started = time.time()
        self.finished: float | None = None
        self.logs: list[str] = []
        self.stages = {k: {"key": k, "label": label, "status": "pending", "progress": 0.0,
                           "detail": None, "indeterminate": False} for k, label in STAGES}
        self._current: str | None = None

    # ---- reporter interface ----
    def log(self, msg: str) -> None:
        self.logs.append(f"{time.strftime('%H:%M:%S')}  {msg}")
        del self.logs[:-500]

    def progress(self, stage: str, fraction: float | None, detail: str | None) -> None:
        st = self.stages.get(stage)
        if st is None:
            return
        # Reaching a stage completes all earlier ones (cached steps finish instantly).
        keys = [k for k, _ in STAGES]
        for k in keys[: keys.index(stage)]:
            if self.stages[k]["status"] != "done":
                self.stages[k].update(status="done", progress=1.0, indeterminate=False)
        self._current = stage
        st["status"] = "done" if fraction is not None and fraction >= 1 else "running"
        if fraction is not None:
            st["progress"] = max(0.0, min(1.0, fraction))
        st["indeterminate"] = fraction is None
        if detail is not None:
            st["detail"] = detail
        elif st["status"] == "done":
            st["detail"] = None  # drop "Waiting for the model" etc. once finished

    # ---- lifecycle ----
    def run(self) -> None:
        REPORTER.set(self)
        try:
            self.result = pipeline.run(self.req.source, self.req.options())
            self.status = "done"
        except ClipperError as e:
            self._fail(str(e))
        except Exception as e:  # noqa: BLE001
            self._fail(f"{type(e).__name__}: {e}")
        finally:
            self.finished = time.time()

    def _fail(self, msg: str) -> None:
        self.status, self.error = "error", msg
        if self._current:
            self.stages[self._current]["status"] = "error"
        self.log(f"ERROR: {msg}")

    def to_dict(self) -> dict:
        stages = list(self.stages.values())
        overall = sum(1.0 if s["status"] == "done" else s["progress"] for s in stages) / len(stages)
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


class JobManager:
    """Runs one job at a time."""

    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.current: Job | None = None
        self._lock = threading.Lock()

    def start(self, req: JobRequest) -> Job | None:
        """Start a job, or return None if one is already running."""
        with self._lock:
            if self.current and self.current.status == "running":
                return None
            job = Job(req)
            self.jobs[job.id] = job
            self.current = job
        threading.Thread(target=job.run, daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)


manager = JobManager()
