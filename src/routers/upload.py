from typing import Optional
from fastapi import APIRouter, UploadFile, File, Depends
from src.config import ORTHANC_URL, ORTHANC_USER, ORTHANC_PASS
from src.auth import verify_token
from src.jobs import create_job
from src.worker import process_upload_task

router = APIRouter(prefix="/upload", tags=["Upload"])


@router.post("/study")
async def upload_study(
    files: list[UploadFile] = File(...),
    target_pacs_url: str = ORTHANC_URL,
    target_pacs_user: str = ORTHANC_USER,
    target_pacs_pass: str = ORTHANC_PASS,
    anonymize: bool = False,
    examination_result: Optional[str] = None,
    notify_url: Optional[str] = None,
    _token=Depends(verify_token),
):
    file_data = [await f.read() for f in files]
    job = create_job("upload", {
        "target_pacs_url": target_pacs_url,
        "anonymize": anonymize,
        "examination_result": examination_result,
        "notify_url": notify_url,
        "file_count": len(file_data),
    })
    process_upload_task.delay(
        job["id"], file_data, target_pacs_url, target_pacs_user,
        target_pacs_pass, anonymize, examination_result, notify_url,
    )
    return {"job_id": job["id"], "status": "queued", "files_received": len(file_data)}