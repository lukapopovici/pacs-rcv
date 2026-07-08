# MSV-med — PACS Backend with AI Indexing

A modular backend system for managing DICOM medical images.
---



## Architecture



---

## Prerequisites

- Python 3.12+
- PostgreSQL 16 with pgvector extension
- Redis 7
- Orthanc (local or remote)
- [uv](https://github.com/astral-sh/uv) package manager
- Docker + Docker Compose (optional, recommended for production)

---
### Docker Compose

Starts all five services (API, worker, Redis, PostgreSQL, Orthanc) in one command:

```bash
cp .env.example .env
# edit .env with your values
docker compose up --build
```

Scale workers independently:
```bash
docker compose up --scale worker=4
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```env
DATABASE_URL=postgresql://msvmed:msvmed@localhost:5432/msvmed
ORTHANC_URL=http://localhost:8042
ORTHANC_USER=orthanc
ORTHANC_PASS=orthanc
REDIS_URL=redis://localhost:6379/0
API_SECRET=your_secret_token_here
```

---

## Running the Application (manually)

Three processes are required:

```bash
uvicorn src.main:app --reload

celery -A src.worker.celery_app worker --loglevel=info

redis-server
```

**Via Docker** (Linux with X11):
```bash
xhost +local:docker
docker compose -f docker-compose.yml -f docker-compose.gui.yml --profile gui up gui
```
