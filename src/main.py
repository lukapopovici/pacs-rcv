import logging
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import ORTHANC_URL, orthanc_auth
from src.routers import studies, instances, upload, forward, jobs, admin, query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(
    title="Dicom API",
    description="Dicom Database endpoint",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO:Restrict in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(studies.router)
app.include_router(instances.router)
app.include_router(upload.router)
app.include_router(forward.router)
app.include_router(jobs.router)
app.include_router(admin.router)
app.include_router(query.router)


@app.get("/", tags=["Health"])
def root():
    return {"status": "MSV-med API running", "version": "1.0.0"}


@app.get("/health", tags=["Health"])
def health():
    try:
        r = httpx.get(f"{ORTHANC_URL}/system", auth=orthanc_auth(), timeout=5)
        pacs_ok = r.status_code == 200
    except Exception:
        pacs_ok = False
    return {"api": "ok", "pacs_reachable": pacs_ok}