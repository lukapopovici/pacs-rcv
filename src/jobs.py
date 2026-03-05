import uuid
from datetime import datetime


JOBS: dict[str, dict] = {}
PACS_CONFIGS: dict[str, dict] = {}


def create_job(job_type: str, params: dict) -> dict:
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id,
        "type": job_type,
        "status": "queued",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "params": params,
        "instances": [],
        "errors": [],
        "progress": {"total": 0, "done": 0},
    }
    JOBS[job_id] = job
    return job


def update_job(job_id: str, **kwargs):
    if job_id in JOBS:
        JOBS[job_id].update(kwargs)
        JOBS[job_id]["updated_at"] = datetime.utcnow().isoformat()