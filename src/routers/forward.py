from fastapi import APIRouter, Depends
from app.auth import verify_token
from app.models import ForwardRequest
from app.jobs import create_job
from app.worker import forward_study_task
from app.config import ORTHANC_URL

router = APIRouter(prefix="/forward", tags=["Forward"])


@router.post("/study")
def forward_study(req: ForwardRequest, _token=Depends(verify_token)):
    job = create_job("forward", req.dict())
    forward_study_task.delay(
        job["id"],
        req.source_study_id,
        req.source_pacs_url or ORTHANC_URL,
        req.target_pacs_url,
        req.target_pacs_user,
        req.target_pacs_pass,
        req.anonymize,
        req.examination_result,
        req.notify_url,
    )
    return {"job_id": job["id"], "status": "queued"}