import httpx
import logging
from fastapi import APIRouter, HTTPException, Depends
from src.config import ORTHANC_URL, orthanc_auth
from src.auth import verify_token

# ---------------------------------------------------------------------------
# DB + embeddings — install these:
#   pip install sqlalchemy asyncpg pgvector sentence-transformers pydicom
# ---------------------------------------------------------------------------
from sqlalchemy import Column, String, DateTime, Text, JSON, Integer, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pgvector.sqlalchemy import Vector
from sentence_transformers import SentenceTransformer
from datetime import datetime
import os

logger = logging.getLogger("msv-med.query")

router = APIRouter(prefix="/query", tags=["Query"])

# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/msvmed")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class DicomStudyRecord(Base):
    """
    One row per DICOM study.
    Layer 1: structured metadata for filtering/querying.
    Layer 2: embedding vector for similarity search (pgvector).
    """
    __tablename__ = "dicom_studies"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    orthanc_study_id    = Column(String, unique=True, index=True, nullable=False)
    study_instance_uid  = Column(String, index=True)
    patient_id          = Column(String, index=True)
    patient_name        = Column(String)
    modality            = Column(String, index=True)      # CT, MR, CR, etc.
    study_date          = Column(String, index=True)      # YYYYMMDD
    study_description   = Column(Text)
    image_comments      = Column(Text)                   # injected exam results live here
    series_count        = Column(Integer)
    instance_count      = Column(Integer)
    raw_tags            = Column(JSON)                   # full tag dump for flexibility
    embedding           = Column(Vector(384))            # 384-dim for all-MiniLM-L6-v2
    ingested_at         = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(engine)  # creates table + pgvector extension must be enabled first


# ---------------------------------------------------------------------------
# Embedding model
# all-MiniLM-L6-v2: small, fast, good for structured text
# Swap for a medical model (e.g. pritamdeka/S-PubMedBert-MS-MARCO) for better
# domain-specific similarity on clinical text.
# ---------------------------------------------------------------------------
embedder = SentenceTransformer("all-MiniLM-L6-v2")


def build_embedding_text(tags: dict) -> str:
    """
    Concatenate the most semantically meaningful DICOM fields into a single
    string for embedding. Tweak the fields to match what your model cares about.
    """
    parts = [
        f"Modality: {tags.get('Modality', '')}",
        f"Description: {tags.get('StudyDescription', '')}",
        f"Series: {tags.get('RequestedProcedureDescription', '')}",
        f"Comments: {tags.get('ImageComments', '')}",
        f"BodyPart: {tags.get('BodyPartExamined', '')}",
        f"Reason: {tags.get('ReasonForTheRequestedProcedure', '')}",
    ]
    return " | ".join(p for p in parts if p.split(": ")[1])  # skip empty fields


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Helpers — pull data from Orthanc
# ---------------------------------------------------------------------------
def _fetch_study_details(study_id: str) -> dict:
    """Pull full study metadata from Orthanc."""
    r = httpx.get(f"{ORTHANC_URL}/studies/{study_id}", auth=orthanc_auth(), timeout=10)
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Study {study_id} not found in PACS")
    r.raise_for_status()
    return r.json()


def _fetch_instance_tags(instance_id: str) -> dict:
    """Pull simplified tag dict from one instance (representative of the study)."""
    r = httpx.get(
        f"{ORTHANC_URL}/instances/{instance_id}/simplified-tags",
        auth=orthanc_auth(),
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def _ingest_study(study_id: str, db: Session) -> DicomStudyRecord:
    """
    Core ingestion logic:
    1. Fetch study + one instance's tags from Orthanc
    2. Build embedding from metadata text
    3. Upsert into Postgres
    """
    # Check for duplicate
    existing = db.query(DicomStudyRecord).filter_by(orthanc_study_id=study_id).first()
    if existing:
        return existing  # idempotent — skip if already ingested

    study = _fetch_study_details(study_id)

    # Pull tags from the first instance for richer metadata
    instances = study.get("Instances", [])
    tags = {}
    if instances:
        try:
            tags = _fetch_instance_tags(instances[0])
        except Exception as e:
            logger.warning(f"Could not fetch instance tags for {study_id}: {e}")

    # Merge Orthanc study-level fields into tags
    patient_main = study.get("PatientMainDicomTags", {})
    study_main = study.get("MainDicomTags", {})
    tags.update(patient_main)
    tags.update(study_main)

    # Build and compute embedding
    embedding_text = build_embedding_text(tags)
    embedding_vector = embedder.encode(embedding_text).tolist()

    record = DicomStudyRecord(
        orthanc_study_id   = study_id,
        study_instance_uid = tags.get("StudyInstanceUID"),
        patient_id         = tags.get("PatientID"),
        patient_name       = tags.get("PatientName"),
        modality           = tags.get("Modality"),
        study_date         = tags.get("StudyDate"),
        study_description  = tags.get("StudyDescription"),
        image_comments     = tags.get("ImageComments"),
        series_count       = len(study.get("Series", [])),
        instance_count     = len(instances),
        raw_tags           = tags,
        embedding          = embedding_vector,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info(f"Ingested study {study_id} → DB id {record.id}")
    return record


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/studies")
def query_studies(_token=Depends(verify_token), db: Session = Depends(get_db)):
    """
    List all studies in Orthanc and return their DB ingestion status.
    Use this to see what has and hasn't been ingested yet.
    """
    r = httpx.get(f"{ORTHANC_URL}/studies", auth=orthanc_auth(), timeout=10)
    r.raise_for_status()
    orthanc_ids = r.json()

    ingested_ids = {
        row.orthanc_study_id
        for row in db.query(DicomStudyRecord.orthanc_study_id).all()
    }

    return [
        {"orthanc_study_id": sid, "ingested": sid in ingested_ids}
        for sid in orthanc_ids
    ]


@router.post("/ingest/{study_id}")
def ingest_study(study_id: str, _token=Depends(verify_token), db: Session = Depends(get_db)):
    """
    Pull a single study from Orthanc, compute its embedding, and store in DB.
    Idempotent — safe to call multiple times on the same study.
    """
    record = _ingest_study(study_id, db)
    return {
        "id": record.id,
        "orthanc_study_id": record.orthanc_study_id,
        "modality": record.modality,
        "study_date": record.study_date,
        "already_existed": record.ingested_at < datetime.utcnow(),
    }


@router.post("/ingest/all")
def ingest_all_studies(_token=Depends(verify_token), db: Session = Depends(get_db)):
    """
    Ingest every study currently in Orthanc.
    Skips already-ingested ones. Returns a summary.
    """
    r = httpx.get(f"{ORTHANC_URL}/studies", auth=orthanc_auth(), timeout=10)
    r.raise_for_status()
    study_ids = r.json()

    results = {"ingested": [], "skipped": [], "failed": []}

    for sid in study_ids:
        already = db.query(DicomStudyRecord).filter_by(orthanc_study_id=sid).first()
        if already:
            results["skipped"].append(sid)
            continue
        try:
            _ingest_study(sid, db)
            results["ingested"].append(sid)
        except Exception as e:
            logger.error(f"Failed to ingest {sid}: {e}")
            results["failed"].append({"id": sid, "error": str(e)})

    return results


@router.get("/search")
def search_similar(
    q: str,
    limit: int = 10,
    modality: str = None,
    _token=Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Semantic similarity search over ingested studies.
    Pass a natural language query (e.g. 'chest CT with pulmonary findings')
    and get back the most similar studies ranked by vector distance.
    Optionally filter by modality (CT, MR, CR, ...).
    """
    query_vector = embedder.encode(q).tolist()

    base_query = db.query(DicomStudyRecord).order_by(
        DicomStudyRecord.embedding.cosine_distance(query_vector)
    )

    if modality:
        base_query = base_query.filter(DicomStudyRecord.modality == modality.upper())

    results = base_query.limit(limit).all()

    return [
        {
            "id": r.id,
            "orthanc_study_id": r.orthanc_study_id,
            "patient_id": r.patient_id,
            "modality": r.modality,
            "study_date": r.study_date,
            "study_description": r.study_description,
            "image_comments": r.image_comments,
            "instance_count": r.instance_count,
        }
        for r in results
    ]


@router.get("/records")
def list_records(
    modality: str = None,
    limit: int = 50,
    offset: int = 0,
    _token=Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    List ingested records with optional modality filter.
    Use this to build training datasets — paginate with limit/offset.
    """
    q = db.query(DicomStudyRecord)
    if modality:
        q = q.filter(DicomStudyRecord.modality == modality.upper())
    total = q.count()
    records = q.offset(offset).limit(limit).all()

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "results": [
            {
                "id": r.id,
                "orthanc_study_id": r.orthanc_study_id,
                "modality": r.modality,
                "study_date": r.study_date,
                "study_description": r.study_description,
                "image_comments": r.image_comments,
                "patient_id": r.patient_id,
                "instance_count": r.instance_count,
                "raw_tags": r.raw_tags,
                "ingested_at": r.ingested_at,
            }
            for r in records
        ],
    }


@router.get("/records/{record_id}")
def get_record(record_id: int, _token=Depends(verify_token), db: Session = Depends(get_db)):
    """Get a single ingested record by its DB id."""
    r = db.query(DicomStudyRecord).filter_by(id=record_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Record not found")
    return {
        "id": r.id,
        "orthanc_study_id": r.orthanc_study_id,
        "study_instance_uid": r.study_instance_uid,
        "patient_id": r.patient_id,
        "modality": r.modality,
        "study_date": r.study_date,
        "study_description": r.study_description,
        "image_comments": r.image_comments,
        "series_count": r.series_count,
        "instance_count": r.instance_count,
        "raw_tags": r.raw_tags,
        "ingested_at": r.ingested_at,
    }


@router.delete("/records/{record_id}")
def delete_record(record_id: int, _token=Depends(verify_token), db: Session = Depends(get_db)):
    """Remove a record from the training DB (does not touch Orthanc)."""
    r = db.query(DicomStudyRecord).filter_by(id=record_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Record not found")
    db.delete(r)
    db.commit()
    return {"deleted": record_id}