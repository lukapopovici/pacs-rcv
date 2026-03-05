from fastapi import APIRouter, HTTPException, Depends
from app.auth import verify_token
from app.jobs import JOBS

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("")
def list_jobs(_token=Depends(verify_token)):
    return sorted(JOBS.values(), key=lambda j: j["created_at"], reverse=True)


@router.get("/{job_id}")
def get_job(job_id: str, _token=Depends(verify_token)):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job