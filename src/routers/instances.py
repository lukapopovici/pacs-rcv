import httpx
from fastapi import APIRouter, HTTPException, Depends
from src.config import ORTHANC_URL, orthanc_auth
from src.auth import verify_token
from src.dicom_utils import dicom_bytes_to_dataset

router = APIRouter(prefix="/instances", tags=["Instances"])


@router.get("/{instance_id}")
def get_instance(instance_id: str, _token=Depends(verify_token)):
    r = httpx.get(f"{ORTHANC_URL}/instances/{instance_id}/file", auth=orthanc_auth())
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Instance not found")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="PACS error")

    ds = dicom_bytes_to_dataset(r.content)
    return {
        "InstanceID": instance_id,
        "SOPInstanceUID": str(ds.get("SOPInstanceUID", "")),
        "StudyInstanceUID": str(ds.get("StudyInstanceUID", "")),
        "SeriesInstanceUID": str(ds.get("SeriesInstanceUID", "")),
        "PatientName": str(ds.get("PatientName", "")),
        "PatientID": str(ds.get("PatientID", "")),
        "Modality": str(ds.get("Modality", "")),
        "StudyDate": str(ds.get("StudyDate", "")),
        "ImageComments": str(ds.get("ImageComments", "")),
    }