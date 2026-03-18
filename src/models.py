from typing import Optional
from pydantic import BaseModel
from src.config import ORTHANC_URL, ORTHANC_USER, ORTHANC_PASS


class ForwardRequest(BaseModel):
    source_study_id: str
    source_pacs_url: Optional[str] = None
    target_pacs_url: str = ORTHANC_URL
    target_pacs_user: str = ORTHANC_USER
    target_pacs_pass: str = ORTHANC_PASS
    anonymize: bool = False
    examination_result: Optional[str] = None
    notify_url: Optional[str] = None


class PACSConfig(BaseModel):
    name: str
    url: str
    username: str
    password: str