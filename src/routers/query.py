"""
query.py — AI indexing and semantic search over DICOM studies.

Architecture:
    SearchStrategy (ABC)
        ├── CosineSearchStrategy      — pgvector cosine distance
        ├── EuclideanSearchStrategy   — pgvector L2 distance
        ├── FullTextSearchStrategy    — PostgreSQL tsvector full-text
        └── HybridSearchStrategy      — cosine + full-text combined

    DicomStudyRepository              — all DB access in one place
    SearchStrategyFactory             — picks strategy by name at runtime
    router endpoints                  — thin, delegate to repo + strategy
"""

import os
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import Column, String, DateTime, Text, JSON, Integer, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pgvector.sqlalchemy import Vector
from fastembed import TextEmbedding

from src.config import ORTHANC_URL, orthanc_auth
from src.auth import verify_token

logger = logging.getLogger("msv-med.query")

router = APIRouter(prefix="/query", tags=["Query"])

                                                                                

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://msvmed:msvmed@localhost:5432/msvmed")
engine       = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine)
Base         = declarative_base()


class DicomStudyRecord(Base):
    __tablename__ = "dicom_studies"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    orthanc_study_id   = Column(String, unique=True, index=True, nullable=False)
    study_instance_uid = Column(String, index=True)
    patient_id         = Column(String, index=True)
    patient_name       = Column(String)
    modality           = Column(String, index=True)
    study_date         = Column(String, index=True)
    study_description  = Column(Text)
    image_comments     = Column(Text)
    series_count       = Column(Integer)
    instance_count     = Column(Integer)
    raw_tags           = Column(JSON)
    embedding          = Column(Vector(384))
    ingested_at        = Column(DateTime, default=datetime.utcnow)


                                                                                

embedder = TextEmbedding("sentence-transformers/all-MiniLM-L6-v2")


def build_embedding_text(tags: dict) -> str:
    parts = [
        f"Modality: {tags.get('Modality', '')}",
        f"Description: {tags.get('StudyDescription', '')}",
        f"Comments: {tags.get('ImageComments', '')}",
        f"BodyPart: {tags.get('BodyPartExamined', '')}",
        f"Reason: {tags.get('ReasonForTheRequestedProcedure', '')}",
    ]
    return " | ".join(p for p in parts if p.split(": ")[1])


def compute_embedding(text: str) -> list[float]:
    return list(embedder.embed([text]))[0].tolist()


                                                                                

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


                                                                                

class DicomStudyRepository:
    """
    Single point of access for all DB operations on DicomStudyRecord.
    Swap the underlying store (e.g. MongoDB, Elasticsearch) here only.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_by_orthanc_id(self, orthanc_id: str) -> Optional[DicomStudyRecord]:
        return self.db.query(DicomStudyRecord).filter_by(orthanc_study_id=orthanc_id).first()

    def get_by_id(self, record_id: int) -> Optional[DicomStudyRecord]:
        return self.db.query(DicomStudyRecord).filter_by(id=record_id).first()

    def list_ingested_ids(self) -> set[str]:
        rows = self.db.query(DicomStudyRecord.orthanc_study_id).all()
        return {r.orthanc_study_id for r in rows}

    def save(self, record: DicomStudyRecord) -> DicomStudyRecord:
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def delete(self, record: DicomStudyRecord):
        self.db.delete(record)
        self.db.commit()

    def list_all(self, modality: str = None, limit: int = 50,
                 offset: int = 0) -> tuple[int, list[DicomStudyRecord]]:
        q = self.db.query(DicomStudyRecord)
        if modality:
            q = q.filter(DicomStudyRecord.modality == modality.upper())
        total = q.count()
        return total, q.offset(offset).limit(limit).all()

    def count_with_embeddings(self) -> int:
        return self.db.query(DicomStudyRecord).filter(
            DicomStudyRecord.embedding.isnot(None)
        ).count()


                                                                                

class SearchStrategy(ABC):
    """
    Abstract base for all search strategies.
    Add a new querying method by subclassing this and registering
    it in SearchStrategyFactory — no other file needs to change.
    """

    @abstractmethod
    def search(self, db: Session, query: str, limit: int,
               modality: str = None) -> list[dict]:
        """
        Execute the search and return a list of result dicts.
        Each dict must contain at least: id, orthanc_study_id,
        modality, study_date, study_description, image_comments, instance_count.
        """
        ...

    def _base_filters(self, q, modality: str = None):
        """Apply common filters shared across strategies."""
        if modality:
            q = q.filter(DicomStudyRecord.modality == modality.upper())
        return q

    @staticmethod
    def _record_to_dict(r: DicomStudyRecord, extra: dict = None) -> dict:
        d = {
            "id":                r.id,
            "orthanc_study_id":  r.orthanc_study_id,
            "patient_id":        r.patient_id,
            "modality":          r.modality,
            "study_date":        r.study_date,
            "study_description": r.study_description,
            "image_comments":    r.image_comments,
            "instance_count":    r.instance_count,
        }
        if extra:
            d.update(extra)
        return d


class CosineSearchStrategy(SearchStrategy):
    """
    Semantic similarity via pgvector cosine distance.
    Best for: natural language clinical queries.
    Example: "CT torace cu noduli pulmonari"
    """

    def search(self, db: Session, query: str, limit: int,
               modality: str = None) -> list[dict]:
        q_vec = compute_embedding(query)
        q_str = "[" + ",".join(str(v) for v in q_vec) + "]"

        sql = text("""
            SELECT
                id,
                1 - (embedding <=> CAST(:qvec AS vector)) AS similarity
            FROM dicom_studies
            WHERE embedding IS NOT NULL
            {modality_filter}
            ORDER BY embedding <=> CAST(:qvec AS vector)
            LIMIT :lim
        """.format(
            modality_filter="AND modality = :mod" if modality else ""
        ))

        params = {"qvec": q_str, "lim": limit}
        if modality:
            params["mod"] = modality.upper()

        rows = db.execute(sql, params).fetchall()
        ids  = {r.id: r.similarity for r in rows}

        records = db.query(DicomStudyRecord).filter(
            DicomStudyRecord.id.in_(ids.keys())
        ).all()
        records.sort(key=lambda r: ids[r.id], reverse=True)

        return [
            self._record_to_dict(r, {"similarity": round(ids[r.id], 4)})
            for r in records
        ]


class EuclideanSearchStrategy(SearchStrategy):
    """
    L2 (Euclidean) distance via pgvector.
    Best for: when embeddings are not normalized and magnitude matters.
    Example: clustering-style nearest neighbor search.
    """

    def search(self, db: Session, query: str, limit: int,
               modality: str = None) -> list[dict]:
        q_vec = compute_embedding(query)
        q_str = "[" + ",".join(str(v) for v in q_vec) + "]"

        sql = text("""
            SELECT
                id,
                (embedding <-> CAST(:qvec AS vector)) AS distance
            FROM dicom_studies
            WHERE embedding IS NOT NULL
            {modality_filter}
            ORDER BY embedding <-> CAST(:qvec AS vector)
            LIMIT :lim
        """.format(
            modality_filter="AND modality = :mod" if modality else ""
        ))

        params = {"qvec": q_str, "lim": limit}
        if modality:
            params["mod"] = modality.upper()

        rows = db.execute(sql, params).fetchall()
        ids  = {r.id: r.distance for r in rows}

        records = db.query(DicomStudyRecord).filter(
            DicomStudyRecord.id.in_(ids.keys())
        ).all()
        records.sort(key=lambda r: ids[r.id])

        return [
            self._record_to_dict(r, {"distance": round(ids[r.id], 4)})
            for r in records
        ]


class FullTextSearchStrategy(SearchStrategy):
    """
    PostgreSQL full-text search via tsvector on study_description
    and image_comments.
    Best for: exact medical term matching, structured keyword queries.
    Example: "pneumonie", "hepatomegalie"
    """

    def search(self, db: Session, query: str, limit: int,
               modality: str = None) -> list[dict]:
        sql = text("""
            SELECT
                id,
                ts_rank(
                    to_tsvector('simple',
                        coalesce(study_description,'') || ' ' ||
                        coalesce(image_comments,'')),
                    plainto_tsquery('simple', :q)
                ) AS rank
            FROM dicom_studies
            WHERE
                to_tsvector('simple',
                    coalesce(study_description,'') || ' ' ||
                    coalesce(image_comments,''))
                @@ plainto_tsquery('simple', :q)
            {modality_filter}
            ORDER BY rank DESC
            LIMIT :lim
        """.format(
            modality_filter="AND modality = :mod" if modality else ""
        ))

        params = {"q": query, "lim": limit}
        if modality:
            params["mod"] = modality.upper()

        rows = db.execute(sql, params).fetchall()
        if not rows:
            return []

        ids = {r.id: r.rank for r in rows}
        records = db.query(DicomStudyRecord).filter(
            DicomStudyRecord.id.in_(ids.keys())
        ).all()
        records.sort(key=lambda r: ids[r.id], reverse=True)

        return [
            self._record_to_dict(r, {"rank": round(ids[r.id], 4)})
            for r in records
        ]


class HybridSearchStrategy(SearchStrategy):
    """
    Combines cosine semantic similarity with full-text rank using
    a weighted sum: final_score = alpha * cosine + (1-alpha) * text_rank.
    Best for: balancing semantic meaning with exact term matching.
    alpha=1.0 → pure cosine; alpha=0.0 → pure full-text.
    """

    def __init__(self, alpha: float = 0.7):
        self.alpha = alpha

    def search(self, db: Session, query: str, limit: int,
               modality: str = None) -> list[dict]:
        cosine_strat  = CosineSearchStrategy()
        fulltext_strat = FullTextSearchStrategy()

        cosine_results   = cosine_strat.search(db, query, limit * 2, modality)
        fulltext_results = fulltext_strat.search(db, query, limit * 2, modality)

                                                
        def normalize(results: list[dict], key: str) -> dict[int, float]:
            if not results:
                return {}
            values = [r[key] for r in results]
            min_v, max_v = min(values), max(values)
            span = max_v - min_v or 1.0
            return {r["id"]: (r[key] - min_v) / span for r in results}

        cosine_scores   = normalize(cosine_results,   "similarity")
        fulltext_scores = normalize(fulltext_results, "rank")

        all_ids = set(cosine_scores) | set(fulltext_scores)
        combined = {
            rid: self.alpha * cosine_scores.get(rid, 0.0)
                 + (1 - self.alpha) * fulltext_scores.get(rid, 0.0)
            for rid in all_ids
        }

        top_ids = sorted(combined, key=combined.get, reverse=True)[:limit]
        records = db.query(DicomStudyRecord).filter(
            DicomStudyRecord.id.in_(top_ids)
        ).all()
        records.sort(key=lambda r: combined[r.id], reverse=True)

        return [
            self._record_to_dict(r, {"score": round(combined[r.id], 4)})
            for r in records
        ]


                                                                                

class SearchStrategyFactory:
    """
    Register new strategies here. The endpoint picks one by name.
    Adding a new strategy = add a subclass above + one line here.
    """

    _registry: dict[str, SearchStrategy] = {
        "cosine":    CosineSearchStrategy(),
        "euclidean": EuclideanSearchStrategy(),
        "fulltext":  FullTextSearchStrategy(),
        "hybrid":    HybridSearchStrategy(alpha=0.7),
    }

    @classmethod
    def get(cls, name: str) -> SearchStrategy:
        strategy = cls._registry.get(name)
        if not strategy:
            available = list(cls._registry.keys())
            raise HTTPException(
                status_code=400,
                detail=f"Unknown search strategy '{name}'. Available: {available}"
            )
        return strategy

    @classmethod
    def available(cls) -> list[str]:
        return list(cls._registry.keys())


                                                                                

def _fetch_study_details(study_id: str) -> dict:
    r = httpx.get(f"{ORTHANC_URL}/studies/{study_id}", auth=orthanc_auth(), timeout=10)
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Study {study_id} not found in PACS")
    r.raise_for_status()
    return r.json()


def _fetch_instance_tags(instance_id: str) -> dict:
    r = httpx.get(
        f"{ORTHANC_URL}/instances/{instance_id}/simplified-tags",
        auth=orthanc_auth(), timeout=10,
    )
    r.raise_for_status()
    return r.json()


                                                                                

def _ingest_study(study_id: str, db: Session) -> DicomStudyRecord:
    repo = DicomStudyRepository(db)

    existing = repo.get_by_orthanc_id(study_id)
    if existing:
        return existing

    study = _fetch_study_details(study_id)
    instances = study.get("Instances", [])
    tags = {}
    if instances:
        try:
            tags = _fetch_instance_tags(instances[0])
        except Exception as e:
            logger.warning(f"Could not fetch instance tags for {study_id}: {e}")

    tags.update(study.get("PatientMainDicomTags", {}))
    tags.update(study.get("MainDicomTags", {}))

    embedding_text   = build_embedding_text(tags)
    embedding_vector = compute_embedding(embedding_text)

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
    return repo.save(record)


                                                                                

@router.get("/strategies", tags=["Query"])
def list_strategies(_token=Depends(verify_token)):
    """List all available search strategies."""
    return {
        "strategies": SearchStrategyFactory.available(),
        "descriptions": {
            "cosine":    "Semantic similarity via pgvector cosine distance",
            "euclidean": "Nearest neighbor via pgvector L2 distance",
            "fulltext":  "PostgreSQL full-text search (exact term matching)",
            "hybrid":    "Weighted combination of cosine + full-text (alpha=0.7)",
        }
    }


@router.get("/studies", tags=["Query"])
def query_studies(_token=Depends(verify_token), db: Session = Depends(get_db)):
    """List all PACS studies with their ingestion status."""
    r = httpx.get(f"{ORTHANC_URL}/studies", auth=orthanc_auth(), timeout=10)
    r.raise_for_status()
    orthanc_ids  = r.json()
    ingested_ids = DicomStudyRepository(db).list_ingested_ids()
    return [
        {"orthanc_study_id": sid, "ingested": sid in ingested_ids}
        for sid in orthanc_ids
    ]


@router.post("/ingest/{study_id}", tags=["Query"])
def ingest_study(study_id: str, _token=Depends(verify_token),
                 db: Session = Depends(get_db)):
    """Ingest a single study from PACS into the vector DB. Idempotent."""
    record = _ingest_study(study_id, db)
    return {
        "id":               record.id,
        "orthanc_study_id": record.orthanc_study_id,
        "modality":         record.modality,
        "study_date":       record.study_date,
    }


@router.post("/ingest/all", tags=["Query"])
def ingest_all_studies(_token=Depends(verify_token), db: Session = Depends(get_db)):
    """Ingest every study currently in PACS. Skips already-ingested ones."""
    r = httpx.get(f"{ORTHANC_URL}/studies", auth=orthanc_auth(), timeout=10)
    r.raise_for_status()
    study_ids    = r.json()
    ingested_ids = DicomStudyRepository(db).list_ingested_ids()
    results      = {"ingested": [], "skipped": [], "failed": []}

    for sid in study_ids:
        if sid in ingested_ids:
            results["skipped"].append(sid)
            continue
        try:
            _ingest_study(sid, db)
            results["ingested"].append(sid)
        except Exception as e:
            logger.error(f"Failed to ingest {sid}: {e}")
            results["failed"].append({"id": sid, "error": str(e)})

    return results


@router.get("/search", tags=["Query"])
def search(
    q:        str            = Query(..., description="Search query text"),
    strategy: str            = Query("cosine", description="Search strategy: cosine | euclidean | fulltext | hybrid"),
    limit:    int            = Query(10, ge=1, le=100),
    modality: Optional[str]  = Query(None, description="Filter by DICOM modality (CT, MR, CR, ...)"),
    _token=Depends(verify_token),
    db: Session = Depends(get_db),
):
    """
    Search indexed studies using the specified strategy.
    Default is cosine semantic similarity.
    Use ?strategy=fulltext for exact term matching,
    ?strategy=hybrid for a combination of both.
    """
    search_strategy = SearchStrategyFactory.get(strategy)
    results = search_strategy.search(db, q, limit, modality)
    return {"strategy": strategy, "count": len(results), "results": results}


@router.get("/records", tags=["Query"])
def list_records(
    modality: Optional[str] = None,
    limit:    int           = 50,
    offset:   int           = 0,
    _token=Depends(verify_token),
    db: Session = Depends(get_db),
):
    """List ingested records, paginated. Use for building ML training datasets."""
    total, records = DicomStudyRepository(db).list_all(modality, limit, offset)
    return {
        "total":   total,
        "offset":  offset,
        "limit":   limit,
        "results": [
            {
                "id":               r.id,
                "orthanc_study_id": r.orthanc_study_id,
                "modality":         r.modality,
                "study_date":       r.study_date,
                "study_description":r.study_description,
                "image_comments":   r.image_comments,
                "patient_id":       r.patient_id,
                "instance_count":   r.instance_count,
                "raw_tags":         r.raw_tags,
                "ingested_at":      r.ingested_at,
            }
            for r in records
        ],
    }


@router.get("/records/{record_id}", tags=["Query"])
def get_record(record_id: int, _token=Depends(verify_token),
               db: Session = Depends(get_db)):
    """Get a single ingested record by its DB id."""
    r = DicomStudyRepository(db).get_by_id(record_id)
    if not r:
        raise HTTPException(status_code=404, detail="Record not found")
    return {
        "id":                r.id,
        "orthanc_study_id":  r.orthanc_study_id,
        "study_instance_uid":r.study_instance_uid,
        "patient_id":        r.patient_id,
        "modality":          r.modality,
        "study_date":        r.study_date,
        "study_description": r.study_description,
        "image_comments":    r.image_comments,
        "series_count":      r.series_count,
        "instance_count":    r.instance_count,
        "raw_tags":          r.raw_tags,
        "ingested_at":       r.ingested_at,
    }


@router.delete("/records/{record_id}", tags=["Query"])
def delete_record(record_id: int, _token=Depends(verify_token),
                  db: Session = Depends(get_db)):
    """Remove a record from the vector DB. Does not touch Orthanc."""
    repo = DicomStudyRepository(db)
    r = repo.get_by_id(record_id)
    if not r:
        raise HTTPException(status_code=404, detail="Record not found")
    repo.delete(r)
    return {"deleted": record_id}