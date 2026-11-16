from fastapi import APIRouter, HTTPException

from clipper.api.jobs import manager
from clipper.api.schemas import JobRequest

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("")
def start_job(req: JobRequest):
    job = manager.start(req)
    if job is None:
        raise HTTPException(409, "A job is already running. Wait for it to finish.")
    return job.to_dict()


@router.get("/current")
def current_job():
    return manager.current.to_dict() if manager.current else None


@router.get("/{job_id}")
def get_job(job_id: str):
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job.to_dict()
