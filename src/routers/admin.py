import uuid
import time
import httpx
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends
from src.auth import verify_token
from src.models import PACSConfig
from src.jobs import JOBS, PACS_CONFIGS
from src.config import ORTHANC_URL, ORTHANC_USER, ORTHANC_PASS, REDIS_URL, orthanc_auth

logger = logging.getLogger("msv-med.admin")

router = APIRouter(prefix="/admin", tags=["Admin"])


                                                                                

@router.post("/pacs")
def add_pacs(config: PACSConfig, _token=Depends(verify_token)):
    pacs_id = str(uuid.uuid4())
    PACS_CONFIGS[pacs_id] = {"id": pacs_id, **config.dict()}
    logger.info(f"PACS config added: {config.name} ({config.url})")
    return {"id": pacs_id}


@router.get("/pacs")
def list_pacs(_token=Depends(verify_token)):
    return [{"id": v["id"], "name": v["name"], "url": v["url"]} for v in PACS_CONFIGS.values()]


@router.delete("/pacs/{pacs_id}")
def delete_pacs(pacs_id: str, _token=Depends(verify_token)):
    if pacs_id not in PACS_CONFIGS:
        raise HTTPException(status_code=404, detail="PACS config not found")
    name = PACS_CONFIGS[pacs_id].get("name")
    del PACS_CONFIGS[pacs_id]
    logger.info(f"PACS config deleted: {name}")
    return {"deleted": pacs_id}


@router.get("/pacs/{pacs_id}/test")
def test_pacs(pacs_id: str, _token=Depends(verify_token)):
    cfg = PACS_CONFIGS.get(pacs_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="PACS config not found")
    try:
        t0 = time.time()
        r = httpx.get(f"{cfg['url']}/system",
                      auth=(cfg["username"], cfg["password"]), timeout=5)
        latency_ms = round((time.time() - t0) * 1000)
        if r.status_code == 200:
            info = r.json()
            return {
                "reachable": True,
                "latency_ms": latency_ms,
                "orthanc_version": info.get("Version"),
                "dicom_aet": info.get("DicomAet"),
                "storage_used": info.get("TotalDiskSizeMB"),
            }
        return {"reachable": False, "status_code": r.status_code}
    except Exception as e:
        return {"reachable": False, "error": str(e)}


                                                                                

@router.get("/stats")
def system_stats(_token=Depends(verify_token)):
                    
    all_jobs = list(JOBS.values())
    total_jobs     = len(all_jobs)
    completed      = sum(1 for j in all_jobs if j["status"] == "completed")
    with_errors    = sum(1 for j in all_jobs if j["status"] == "completed_with_errors")
    failed         = sum(1 for j in all_jobs if j["status"] == "failed")
    queued         = sum(1 for j in all_jobs if j["status"] == "queued")
    processing     = sum(1 for j in all_jobs if j["status"] == "processing")

                  
    finished = completed + with_errors + failed
    success_rate = round((completed / finished * 100), 1) if finished > 0 else None

                               
    total_instances = sum(
        len(j.get("instances", [])) for j in all_jobs
    )
    total_errors = sum(
        len(j.get("errors", [])) for j in all_jobs
    )

                      
    cutoff = datetime.utcnow() - timedelta(hours=24)
    recent_jobs = [
        j for j in all_jobs
        if datetime.fromisoformat(j["created_at"]) > cutoff
    ]

                    
    orthanc_info = {}
    try:
        r = httpx.get(f"{ORTHANC_URL}/system", auth=orthanc_auth(), timeout=4)
        if r.status_code == 200:
            d = r.json()
            orthanc_info = {
                "reachable": True,
                "version": d.get("Version"),
                "aet": d.get("DicomAet"),
            }
        else:
            orthanc_info = {"reachable": False}
    except Exception as e:
        orthanc_info = {"reachable": False, "error": str(e)}

                            
    orthanc_counts = {}
    try:
        studies_r   = httpx.get(f"{ORTHANC_URL}/studies",   auth=orthanc_auth(), timeout=4)
        instances_r = httpx.get(f"{ORTHANC_URL}/instances", auth=orthanc_auth(), timeout=4)
        orthanc_counts = {
            "studies":   len(studies_r.json())   if studies_r.status_code   == 200 else "?",
            "instances": len(instances_r.json()) if instances_r.status_code == 200 else "?",
        }
    except Exception:
        orthanc_counts = {"studies": "?", "instances": "?"}

                  
    redis_ok = False
    try:
        import redis as redis_lib
        r_client = redis_lib.from_url(REDIS_URL, socket_timeout=2)
        r_client.ping()
        redis_ok = True
    except Exception:
        pass

                  
    pacs_count = len(PACS_CONFIGS)

    return {
        "jobs": {
            "total":            total_jobs,
            "completed":        completed,
            "completed_with_errors": with_errors,
            "failed":           failed,
            "queued":           queued,
            "processing":       processing,
            "success_rate_pct": success_rate,
            "total_instances":  total_instances,
            "total_errors":     total_errors,
            "last_24h":         len(recent_jobs),
        },
        "orthanc":  {**orthanc_info, **orthanc_counts},
        "redis":    {"reachable": redis_ok},
        "pacs_configs": pacs_count,
        "generated_at": datetime.utcnow().isoformat(),
    }


                                                                                

@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, _token=Depends(verify_token)):
    """Remove a job record from the store."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    del JOBS[job_id]
    return {"deleted": job_id}


@router.delete("/jobs")
def purge_jobs(status: str = None, _token=Depends(verify_token)):
    if status:
        to_delete = [jid for jid, j in JOBS.items() if j["status"] == status]
    else:
        to_delete = list(JOBS.keys())
    for jid in to_delete:
        del JOBS[jid]
    logger.info(f"Purged {len(to_delete)} jobs (filter: {status or 'all'})")
    return {"deleted_count": len(to_delete)}


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, _token=Depends(verify_token)):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] not in ("failed", "completed_with_errors"):
        raise HTTPException(status_code=400, detail=f"Cannot retry job with status '{job['status']}'")

    from src.jobs import create_job
    from src.worker import process_upload_task, forward_study_task

    params = job.get("params", {})
    new_job = create_job(job["type"], params)

    if job["type"] == "forward":
        forward_study_task.delay(
            new_job["id"],
            params.get("source_study_id"),
            params.get("source_pacs_url", ORTHANC_URL),
            params.get("target_pacs_url", ORTHANC_URL),
            params.get("target_pacs_user", ORTHANC_USER),
            params.get("target_pacs_pass", ORTHANC_PASS),
            params.get("anonymize", False),
            params.get("examination_result"),
            params.get("notify_url"),
        )

    logger.info(f"Retried job {job_id} → new job {new_job['id']}")
    return {"original_job_id": job_id, "new_job_id": new_job["id"]}


                                                                                

@router.get("/audit")
def audit_log(limit: int = 50, status: str = None, _token=Depends(verify_token)):
    jobs = list(JOBS.values())

    if status:
        jobs = [j for j in jobs if j["status"] == status]

    jobs_sorted = sorted(jobs, key=lambda j: j["created_at"], reverse=True)[:limit]

    return [
        {
            "job_id":     j["id"],
            "type":       j["type"],
            "status":     j["status"],
            "instances":  len(j.get("instances", [])),
            "errors":     len(j.get("errors", [])),
            "created_at": j["created_at"],
            "updated_at": j["updated_at"],
            "target_pacs": j.get("params", {}).get("target_pacs_url"),
            "anonymized":  j.get("params", {}).get("anonymize", False),
        }
        for j in jobs_sorted
    ]


                                                                                

@router.get("/workers")
def worker_health(_token=Depends(verify_token)):
    """
    Query Celery worker status via Redis inspect.
    Returns active workers and their active tasks.
    """
    try:
        from src.worker import celery_app
        inspect = celery_app.control.inspect(timeout=3)
        active  = inspect.active()  or {}
        stats   = inspect.stats()   or {}
        registered = inspect.registered() or {}

        workers = []
        for worker_name, tasks in active.items():
            workers.append({
                "name":         worker_name,
                "status":       "online",
                "active_tasks": len(tasks),
                "tasks":        [t.get("name") for t in tasks],
                "processed":    stats.get(worker_name, {}).get("total", {}),
            })

        if not workers:
            return {"workers": [], "note": "No workers online or inspect timed out."}

        return {"workers": workers, "total_online": len(workers)}

    except Exception as e:
        return {"workers": [], "error": str(e)}
