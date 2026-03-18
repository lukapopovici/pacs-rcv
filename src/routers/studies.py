import httpx
from fastapi import APIRouter, HTTPException, Depends
from src.config import ORTHANC_URL, orthanc_auth
from src.auth import verify_token

router = APIRouter(prefix="/studies", tags=["Studies"])


@router.get("")
def list_studies(_token=Depends(verify_token)):
    r = httpx.get(f"{ORTHANC_URL}/studies", auth=orthanc_auth())
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to fetch studies from PACS")
    return r.json()


@router.get("/{study_id}")
def get_study(study_id: str, _token=Depends(verify_token)):
    r = httpx.get(f"{ORTHANC_URL}/studies/{study_id}", auth=orthanc_auth())
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Study not found")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="PACS error")
    return r.json()