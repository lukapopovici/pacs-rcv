import os

ORTHANC_URL = os.getenv("ORTHANC_URL", "http://localhost:8042")
ORTHANC_USER = os.getenv("ORTHANC_USER", "orthanc")
ORTHANC_PASS = os.getenv("ORTHANC_PASS", "orthanc")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
API_SECRET = os.getenv("API_SECRET", "changeme")

def orthanc_auth():
    return (ORTHANC_USER, ORTHANC_PASS)