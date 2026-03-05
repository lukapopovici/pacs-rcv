import uuid
import httpx
from fastapi import APIRouter, HTTPException, Depends
from app.auth import verify_token
from app.models import PACSConfig
from app.jobs import PACS_CONFIGS

router = APIRouter(prefix="/admin/pacs", tags=["Admin"])


@router.post("")
def add_pacs(config: PACSConfig, _token=Depends(verify_token)):
    pacs_id = str(uuid.uuid4())
    PACS_CONFIGS[pacs_id] = {"id": pacs_id, **config.dict()}
    return {"id": pacs_id}


@router.get("")
def list_pacs(_token=Depends(verify_token)):
    # NNEVER EVER expose passwords
    return [{"id": v["id"], "name": v["name"], "url": v["url"]} for v in PACS_CONFIGS.values()]


@router.delete("/{pacs_id}")
def delete_pacs(pacs_id: str, _token=Depends(verify_token)):
    if pacs_id not in PACS_CONFIGS:
        raise HTTPException(status_code=404, detail="PACS config not found")
    del PACS_CONFIGS[pacs_id]
    return {"deleted": pacs_id}


@router.get("/{pacs_id}/test")
def test_pacs(pacs_id: str, _token=Depends(verify_token)):
    cfg = PACS_CONFIGS.get(pacs_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="PACS config not found")
    try:
        r = httpx.get(f"{cfg['url']}/system", auth=(cfg["username"], cfg["password"]), timeout=5)
        return {"reachable": r.status_code == 200, "status_code": r.status_code}
    except Exception as e:
        return {"reachable": False, "error": str(e)}