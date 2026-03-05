import logging
import httpx
from celery import Celery
from app.config import REDIS_URL, orthanc_auth
from app.jobs import update_job
from app.dicom_utils import (
    dicom_bytes_to_dataset, dataset_to_bytes,
    anonymize_dataset, embed_examination_result,
)

logger = logging.getLogger("msv-med.worker")

celery_app = Celery("msv-med", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.task_acks_late = True


def _push_instance(raw: bytes, target_url: str, target_user: str, target_pass: str,
                   anonymize: bool, examination_result: str | None) -> dict:
    ds = dicom_bytes_to_dataset(raw)
    instance_uid = str(ds.get("SOPInstanceUID", "unknown"))

    if anonymize:
        ds = anonymize_dataset(ds)
    if examination_result:
        ds = embed_examination_result(ds, examination_result)

    modified = dataset_to_bytes(ds)
    r = httpx.post(
        f"{target_url}/instances",
        content=modified,
        headers={"Content-Type": "application/dicom"},
        auth=(target_user, target_pass),
        timeout=30,
    )
    return {"instance_uid": instance_uid, "status_code": r.status_code, "ok": r.status_code == 200}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def process_upload_task(self, job_id, file_data_list, target_pacs_url,
                        target_pacs_user, target_pacs_pass,
                        anonymize, examination_result, notify_url):
    update_job(job_id, status="processing", progress={"total": len(file_data_list), "done": 0})
    errors, results = [], []

    for idx, raw in enumerate(file_data_list):
        try:
            result = _push_instance(raw, target_pacs_url, target_pacs_user, target_pacs_pass,
                                    anonymize, examination_result)
            results.append(result)
            if not result["ok"] and result["status_code"] >= 500:
                raise Exception(f"PACS 5xx: {result['status_code']}")
        except Exception as exc:
            logger.error(f"Job {job_id} instance {idx} failed: {exc}")
            errors.append({"index": idx, "error": str(exc)})
            try:
                raise self.retry(exc=exc)
            except self.MaxRetriesExceededError:
                pass

        update_job(job_id, progress={"total": len(file_data_list), "done": idx + 1})

    _finish_job(job_id, results, errors, notify_url)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=15)
def forward_study_task(self, job_id, source_study_id, source_pacs_url,
                       target_pacs_url, target_pacs_user, target_pacs_pass,
                       anonymize, examination_result, notify_url):
    update_job(job_id, status="fetching_instances")

    try:
        r = httpx.get(f"{source_pacs_url}/studies/{source_study_id}/instances",
                      auth=orthanc_auth(), timeout=15)
        r.raise_for_status()
        instances = r.json()
    except Exception as exc:
        update_job(job_id, status="failed", errors=[{"error": str(exc)}])
        raise

    update_job(job_id, status="processing", progress={"total": len(instances), "done": 0})
    errors, results = [], []

    for idx, meta in enumerate(instances):
        instance_id = meta.get("ID") or meta.get("id", "")
        try:
            dl = httpx.get(f"{source_pacs_url}/instances/{instance_id}/file",
                           auth=orthanc_auth(), timeout=30)
            dl.raise_for_status()
            result = _push_instance(dl.content, target_pacs_url, target_pacs_user,
                                    target_pacs_pass, anonymize, examination_result)
            results.append(result)
            if not result["ok"] and result["status_code"] >= 500:
                raise Exception(f"PACS 5xx: {result['status_code']}")
        except Exception as exc:
            logger.error(f"Job {job_id} forward {instance_id} failed: {exc}")
            errors.append({"instance_id": instance_id, "error": str(exc)})
            try:
                raise self.retry(exc=exc)
            except self.MaxRetriesExceededError:
                pass

        update_job(job_id, progress={"total": len(instances), "done": idx + 1})

    _finish_job(job_id, results, errors, notify_url)


def _finish_job(job_id, results, errors, notify_url):
    status = "completed" if not errors else "completed_with_errors"
    update_job(job_id, status=status, instances=results, errors=errors)
    if notify_url:
        try:
            httpx.post(notify_url, json={"job_id": job_id, "status": status}, timeout=10)
        except Exception as e:
            logger.warning(f"Webhook failed for {job_id}: {e}")