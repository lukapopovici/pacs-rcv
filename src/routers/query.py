import httpx
from fastapi import APIRouter, HTTPException, Depends
from src.config import ORTHANC_URL, orthanc_auth
from src.auth import verify_token

router = APIRouter(prefix="/query", tags=["Query"])

