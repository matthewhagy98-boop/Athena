# Evidence Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the evidence engine — a Python pipeline that ingests biomedical papers from PubMed/PMC, Semantic Scholar, and ClinicalTrials.gov, classifies and scores each for evidence strength, and maintains a precomputed per-topic consensus with contradiction flagging.

**Architecture:** Five components per the spec — Topic Registry, Source Adapters, Classification & Scoring Engine, Consensus Synthesizer, Orchestrator — backed by Postgres, driven by a daily scheduled script, using Claude for classification fallback, sample-size extraction, risk-of-bias detection, and consensus synthesis.

**Tech Stack:** Python 3.12, uv (packaging), SQLAlchemy 2.0 + Alembic (Postgres), httpx + tenacity (HTTP/retry), anthropic SDK (Claude), pytest + respx (testing).

## Global Constraints

- Domain is biomedical only for this plan (per spec section 2).
- Data sources: PubMed/PMC E-utilities, Semantic Scholar Graph API, ClinicalTrials.gov API v2 (per spec section 2).
- Journal reputation signal is SJR (SCImago), not Impact Factor (per spec section 2).
- Topics are normalized to MeSH terms (per spec section 2); mapping uses NLM's own `db=mesh` ESearch endpoint rather than a UMLS account — see note at Task 4.
- Scoring is deterministic base score + LLM risk-of-bias modifiers (Approach B, per spec section 2), not pure deterministic or a learned model.
- Consensus is precomputed per topic, grounded only in top-tier evidence, not generated fresh per query (per spec section 2).
- Ingestion is topic-driven, not full-corpus (per spec section 2).
- Scheduling is a single daily scheduled script, not a task queue (per this plan's tech-stack decision).
- LLM provider is Anthropic Claude, model `claude-sonnet-4-6` by default, configurable via `ANTHROPIC_MODEL` env var.
- All out-of-scope items from spec section 8 (other domains, web app, digest, enterprise API, search indexing, profile management) are not touched by this plan.

---

## Task 1: Project Scaffolding & Database Connection

**Files:**
- Create: `pyproject.toml`
- Create: `docker-compose.yml`
- Create: `evidence_engine/__init__.py`
- Create: `evidence_engine/config.py`
- Create: `evidence_engine/db/__init__.py`
- Create: `evidence_engine/db/session.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `evidence_engine.config.Settings` (pydantic-settings class with fields `database_url: str`, `anthropic_api_key: str`, `anthropic_model: str = "claude-sonnet-4-6"`, `ncbi_api_key: str | None`, `semantic_scholar_api_key: str | None`), and a module-level `get_settings() -> Settings` (cached via `functools.lru_cache`).
- Produces: `evidence_engine.db.session.engine` (SQLAlchemy `Engine`), `evidence_engine.db.session.SessionLocal` (`sessionmaker`), `evidence_engine.db.session.get_session() -> Generator[Session, None, None]` context-manager-style function.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "evidence-engine"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "sqlalchemy>=2.0",
    "psycopg[binary]>=3.1",
    "alembic>=1.13",
    "httpx>=0.27",
    "tenacity>=8.2",
    "anthropic>=0.34",
    "pydantic-settings>=2.4",
    "defusedxml>=0.7",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "respx>=0.21",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
markers = ["eval: golden-set accuracy checks, run explicitly via -m eval"]
addopts = "-m 'not eval'"
```

- [ ] **Step 2: Create `docker-compose.yml` for local Postgres**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: evidence_engine
      POSTGRES_PASSWORD: evidence_engine
      POSTGRES_DB: evidence_engine
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

- [ ] **Step 3: Create `.env.example`**

```bash
DATABASE_URL=postgresql+psycopg://evidence_engine:evidence_engine@localhost:5432/evidence_engine
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6
NCBI_API_KEY=
SEMANTIC_SCHOLAR_API_KEY=
```

- [ ] **Step 4: Write `evidence_engine/config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    anthropic_api_key: str
    anthropic_model: str = "claude-sonnet-4-6"
    ncbi_api_key: str | None = None
    semantic_scholar_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Write the failing test for config**

```python
# tests/test_config.py
import os

from evidence_engine.config import Settings


def test_settings_loads_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    settings = Settings()
    assert settings.database_url == "postgresql+psycopg://u:p@localhost:5432/db"
    assert settings.anthropic_model == "claude-sonnet-4-6"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine'` (package not yet installed) or import error — confirms the test runs before the module exists.

- [ ] **Step 7: Install the package in editable mode and re-run**

Run: `uv sync --extra dev && uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 8: Write `evidence_engine/db/session.py`**

```python
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from evidence_engine.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 9: Start local Postgres and write a connectivity test**

Run: `docker compose up -d postgres`

```python
# tests/conftest.py
import pytest
from sqlalchemy import text

from evidence_engine.db.session import engine


@pytest.fixture
def db_connection():
    with engine.connect() as conn:
        yield conn
```

```python
# tests/test_db_connection.py
from sqlalchemy import text


def test_can_connect_to_database(db_connection):
    result = db_connection.execute(text("SELECT 1"))
    assert result.scalar() == 1
```

- [ ] **Step 10: Run test to verify it passes**

Run: `uv run pytest tests/test_db_connection.py -v`
Expected: PASS (requires `docker compose up -d postgres` running and a local `.env` copied from `.env.example` with `DATABASE_URL` set)

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml docker-compose.yml .env.example evidence_engine/ tests/
git commit -m "feat: project scaffolding, config, and db connection"
```

---

## Task 2: Database Models & Migrations

**Files:**
- Create: `evidence_engine/db/models.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/versions/0001_initial_schema.py`
- Modify: `tests/conftest.py`
- Test: `tests/db/test_models.py`

**Interfaces:**
- Consumes: `evidence_engine.db.session.engine` (Task 1).
- Produces: `evidence_engine.db.models.Base` (declarative base), and ORM classes `Topic`, `Paper`, `PaperTopic`, `Score`, `ConsensusSnapshot`, `ChangeEvent`, plus enums `StudyType`, `EvidenceTier`, `ChangeEventType` — all imported by every later task that touches the database.

- [ ] **Step 1: Write `evidence_engine/db/models.py`**

```python
import enum
import uuid
from datetime import date, datetime

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class StudyType(str, enum.Enum):
    META_ANALYSIS = "meta_analysis"
    SYSTEMATIC_REVIEW = "systematic_review"
    RCT = "rct"
    COHORT = "cohort"
    CASE_CONTROL = "case_control"
    CASE_SERIES = "case_series"
    OPINION_EDITORIAL = "opinion_editorial"
    UNKNOWN = "unknown"


class EvidenceTier(str, enum.Enum):
    ESTABLISHED = "established"
    EMERGING = "emerging"
    SPECULATIVE = "speculative"


class ChangeEventType(str, enum.Enum):
    NEW_PAPER = "new_paper"
    CONSENSUS_UPDATED = "consensus_updated"
    CONTRADICTION_FLAGGED = "contradiction_flagged"
    PAPER_RETRACTED = "paper_retracted"


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mesh_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    canonical_label: Mapped[str] = mapped_column(String, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    status: Mapped[str] = mapped_column(String, default="active")
    last_checked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pmid: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    doi: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    nct_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    semantic_scholar_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    abstract: Mapped[str | None] = mapped_column(String, nullable=True)
    authors: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    journal: Mapped[str | None] = mapped_column(String, nullable=True)
    journal_issn: Mapped[str | None] = mapped_column(String, nullable=True)
    pub_date: Mapped[date | None] = mapped_column(nullable=True)
    publication_types: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    is_retracted: Mapped[bool] = mapped_column(default=False)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)


class PaperTopic(Base):
    __tablename__ = "paper_topics"
    __table_args__ = (UniqueConstraint("paper_id", "topic_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("papers.id"))
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"))


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paper_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("papers.id"), unique=True)
    study_type: Mapped[StudyType] = mapped_column(default=StudyType.UNKNOWN)
    sample_size: Mapped[int | None] = mapped_column(nullable=True)
    citation_count: Mapped[int] = mapped_column(default=0)
    journal_sjr: Mapped[float | None] = mapped_column(nullable=True)
    base_score: Mapped[float] = mapped_column(default=0.0)
    risk_of_bias_flags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    final_score: Mapped[float] = mapped_column(default=0.0)
    evidence_tier: Mapped[EvidenceTier] = mapped_column(default=EvidenceTier.SPECULATIVE)
    quality_breakdown: Mapped[str | None] = mapped_column(String, nullable=True)
    is_pending: Mapped[bool] = mapped_column(default=False)
    scored_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    model_version: Mapped[str] = mapped_column(String, nullable=False)

    paper: Mapped["Paper"] = relationship()


class ConsensusSnapshot(Base):
    __tablename__ = "consensus_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"))
    consensus_text: Mapped[str | None] = mapped_column(String, nullable=True)
    is_insufficient_evidence: Mapped[bool] = mapped_column(default=False)
    supporting_paper_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    contradiction_notes: Mapped[str | None] = mapped_column(String, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    model_version: Mapped[str] = mapped_column(String, nullable=False)


class ChangeEvent(Base):
    __tablename__ = "change_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"))
    paper_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("papers.id"), nullable=True)
    event_type: Mapped[ChangeEventType] = mapped_column()
    detected_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
```

- [ ] **Step 2: Initialize Alembic**

Run: `uv run alembic init alembic`
Expected: creates `alembic.ini` and `alembic/` directory with `env.py`, `script.py.mako`, `versions/`.

- [ ] **Step 3: Point `alembic/env.py` at the models and settings**

In `alembic/env.py`, replace the `target_metadata = None` line and the URL configuration:

```python
from evidence_engine.config import get_settings
from evidence_engine.db.models import Base

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata
```

- [ ] **Step 4: Generate the initial migration**

Run: `uv run alembic revision --autogenerate -m "initial schema"`
Expected: creates `alembic/versions/0001_initial_schema.py` (filename will include a hash prefix) containing `op.create_table(...)` calls for all six tables.

- [ ] **Step 5: Apply the migration**

Run: `uv run alembic upgrade head`
Expected: exits 0; all six tables now exist in the local Postgres database.

- [ ] **Step 6: Add a transactional test fixture to `tests/conftest.py`**

```python
# tests/conftest.py (append)
import pytest
from sqlalchemy.orm import Session

from evidence_engine.db.session import engine


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()
```

- [ ] **Step 7: Write the failing round-trip test**

```python
# tests/db/test_models.py
import uuid

from evidence_engine.db.models import EvidenceTier, Paper, StudyType, Topic


def test_topic_and_paper_round_trip(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="D009203")
    db_session.add(topic)
    db_session.flush()

    paper = Paper(
        pmid="12345678",
        title="A study of something",
        abstract="Background... Methods... Results...",
        authors=["Smith J", "Doe A"],
        journal="The Lancet",
        publication_types=["Randomized Controlled Trial"],
    )
    db_session.add(paper)
    db_session.flush()

    fetched_topic = db_session.get(Topic, topic.id)
    fetched_paper = db_session.get(Paper, paper.id)

    assert fetched_topic.canonical_label == "Myocardial Infarction"
    assert fetched_paper.pmid == "12345678"
    assert fetched_paper.publication_types == ["Randomized Controlled Trial"]
```

- [ ] **Step 8: Run test to verify it fails**

Run: `uv run pytest tests/db/test_models.py -v`
Expected: FAIL (`ModuleNotFoundError` or `ImportError`) before `evidence_engine/db/models.py` exists — since Step 1 already created it, instead run this before Step 1 in practice, or confirm it fails if the migration from Step 5 hasn't run yet (`relation "topics" does not exist`).

- [ ] **Step 9: Run test to verify it passes**

Run: `uv run pytest tests/db/test_models.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add evidence_engine/db/models.py alembic.ini alembic/ tests/conftest.py tests/db/test_models.py
git commit -m "feat: add database models and initial migration"
```

---

## Task 3: SJR Journal Reference Data

**Files:**
- Create: `evidence_engine/db/models.py` (modify — add table)
- Create: `alembic/versions/0002_journal_sjr.py`
- Create: `evidence_engine/reference/__init__.py`
- Create: `evidence_engine/reference/sjr_loader.py`
- Create: `tests/fixtures/sjr_sample.csv`
- Test: `tests/reference/test_sjr_loader.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.Base` (Task 2).
- Produces: `evidence_engine.db.models.JournalSJR` ORM class (fields: `issn: str`, `journal_name: str`, `sjr_score: float`, `year: int`), and `evidence_engine.reference.sjr_loader.load_sjr_csv(session, csv_path: str) -> int` (returns rows upserted). Later scoring tasks look up SJR by ISSN via `session.query(JournalSJR).filter_by(issn=...)`.

- [ ] **Step 1: Add the `JournalSJR` model**

Append to `evidence_engine/db/models.py`:

```python
class JournalSJR(Base):
    __tablename__ = "journal_sjr"
    __table_args__ = (UniqueConstraint("issn", "year"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    issn: Mapped[str] = mapped_column(String, nullable=False)
    journal_name: Mapped[str] = mapped_column(String, nullable=False)
    sjr_score: Mapped[float] = mapped_column(nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
```

- [ ] **Step 2: Generate and apply the migration**

Run: `uv run alembic revision --autogenerate -m "journal sjr"`
Run: `uv run alembic upgrade head`
Expected: both exit 0; `journal_sjr` table exists.

- [ ] **Step 3: Create a small fixture CSV matching Scimago's export format**

```csv
# tests/fixtures/sjr_sample.csv
Issn,Title,SJR,Year
0140-6736,The Lancet,10.5,2024
1533-4406,New England Journal of Medicine,12.3,2024
```

- [ ] **Step 4: Write the failing test**

```python
# tests/reference/test_sjr_loader.py
from evidence_engine.db.models import JournalSJR
from evidence_engine.reference.sjr_loader import load_sjr_csv


def test_load_sjr_csv_upserts_rows(db_session):
    count = load_sjr_csv(db_session, "tests/fixtures/sjr_sample.csv")
    db_session.flush()

    assert count == 2
    lancet = db_session.query(JournalSJR).filter_by(issn="0140-6736").one()
    assert lancet.sjr_score == 10.5
    assert lancet.year == 2024


def test_load_sjr_csv_is_idempotent(db_session):
    load_sjr_csv(db_session, "tests/fixtures/sjr_sample.csv")
    db_session.flush()
    count = load_sjr_csv(db_session, "tests/fixtures/sjr_sample.csv")
    db_session.flush()

    assert count == 2
    assert db_session.query(JournalSJR).count() == 2
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv run pytest tests/reference/test_sjr_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.reference.sjr_loader'`

- [ ] **Step 6: Write `evidence_engine/reference/sjr_loader.py`**

```python
import csv

from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.db.models import JournalSJR


def load_sjr_csv(session: Session, csv_path: str) -> int:
    count = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            issn = row["Issn"].strip()
            year = int(row["Year"])
            existing = session.execute(
                select(JournalSJR).where(JournalSJR.issn == issn, JournalSJR.year == year)
            ).scalar_one_or_none()

            if existing:
                existing.sjr_score = float(row["SJR"])
                existing.journal_name = row["Title"]
            else:
                session.add(
                    JournalSJR(
                        issn=issn,
                        journal_name=row["Title"],
                        sjr_score=float(row["SJR"]),
                        year=year,
                    )
                )
            count += 1
    return count
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/reference/test_sjr_loader.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add evidence_engine/db/models.py alembic/versions/ evidence_engine/reference/ tests/fixtures/sjr_sample.csv tests/reference/test_sjr_loader.py
git commit -m "feat: add SJR journal reference data loader"
```

---

## Task 4: MeSH Topic Normalization & Topic Registry

**Note on spec deviation:** the spec (section 2) names UMLS Metathesaurus as the fallback for terms PubMed doesn't resolve. This task implements MeSH lookup entirely through NLM's own `db=mesh` ESearch/ESummary endpoints instead, which requires no separate UMLS account/API key and covers the same job (resolving free text to a canonical MeSH descriptor) for the terms this product actually needs. UMLS integration is not part of this plan; it can be added later behind the same `resolve_to_mesh` interface if a term arises that `db=mesh` can't resolve.

**Files:**
- Create: `evidence_engine/topics/__init__.py`
- Create: `evidence_engine/topics/mesh.py`
- Create: `evidence_engine/topics/registry.py`
- Test: `tests/topics/test_mesh.py`
- Test: `tests/topics/test_registry.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.Topic` (Task 2), `evidence_engine.config.get_settings` (Task 1).
- Produces: `evidence_engine.topics.mesh.resolve_to_mesh(term: str) -> MeshResolution | None` where `MeshResolution` is a dataclass with `mesh_id: str`, `canonical_label: str`. Produces `evidence_engine.topics.registry.get_or_create_topic(session, free_text: str) -> Topic` — the entry point every later "add an interest/search" call uses.

- [ ] **Step 1: Write the failing test for MeSH resolution**

```python
# tests/topics/test_mesh.py
import httpx
import respx

from evidence_engine.topics.mesh import resolve_to_mesh

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


@respx.mock
def test_resolve_to_mesh_returns_canonical_term():
    respx.get(ESEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json={"esearchresult": {"idlist": ["68009203"]}},
        )
    )
    respx.get(ESUMMARY_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "uids": ["68009203"],
                    "68009203": {"ds_meshterms": ["Myocardial Infarction"]},
                }
            },
        )
    )

    result = resolve_to_mesh("heart attack")

    assert result is not None
    assert result.mesh_id == "68009203"
    assert result.canonical_label == "Myocardial Infarction"


@respx.mock
def test_resolve_to_mesh_returns_none_when_no_match():
    respx.get(ESEARCH_URL).mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": []}})
    )

    result = resolve_to_mesh("not a real medical term xyz")

    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/topics/test_mesh.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.topics.mesh'`

- [ ] **Step 3: Write `evidence_engine/topics/mesh.py`**

```python
from dataclasses import dataclass

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from evidence_engine.config import get_settings

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


@dataclass
class MeshResolution:
    mesh_id: str
    canonical_label: str


def _api_params() -> dict:
    settings = get_settings()
    params = {}
    if settings.ncbi_api_key:
        params["api_key"] = settings.ncbi_api_key
    return params


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def resolve_to_mesh(term: str) -> MeshResolution | None:
    with httpx.Client(timeout=10.0) as client:
        search_resp = client.get(
            ESEARCH_URL,
            params={"db": "mesh", "term": term, "retmode": "json", **_api_params()},
        )
        search_resp.raise_for_status()
        id_list = search_resp.json()["esearchresult"]["idlist"]
        if not id_list:
            return None

        mesh_uid = id_list[0]
        summary_resp = client.get(
            ESUMMARY_URL,
            params={"db": "mesh", "id": mesh_uid, "retmode": "json", **_api_params()},
        )
        summary_resp.raise_for_status()
        entry = summary_resp.json()["result"][mesh_uid]
        terms = entry.get("ds_meshterms", [])
        if not terms:
            return None

        return MeshResolution(mesh_id=mesh_uid, canonical_label=terms[0])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/topics/test_mesh.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for the topic registry**

```python
# tests/topics/test_registry.py
from unittest.mock import patch

from evidence_engine.db.models import Topic
from evidence_engine.topics.mesh import MeshResolution
from evidence_engine.topics.registry import get_or_create_topic


def test_get_or_create_topic_creates_new_topic(db_session):
    with patch(
        "evidence_engine.topics.registry.resolve_to_mesh",
        return_value=MeshResolution(mesh_id="68009203", canonical_label="Myocardial Infarction"),
    ):
        topic = get_or_create_topic(db_session, "heart attack")

    assert topic.mesh_id == "68009203"
    assert topic.canonical_label == "Myocardial Infarction"
    assert "heart attack" in topic.aliases


def test_get_or_create_topic_reuses_existing_topic_by_mesh_id(db_session):
    existing = Topic(mesh_id="68009203", canonical_label="Myocardial Infarction", aliases=["heart attack"])
    db_session.add(existing)
    db_session.flush()

    with patch(
        "evidence_engine.topics.registry.resolve_to_mesh",
        return_value=MeshResolution(mesh_id="68009203", canonical_label="Myocardial Infarction"),
    ):
        topic = get_or_create_topic(db_session, "myocardial infarction")

    assert topic.id == existing.id
    assert "myocardial infarction" in topic.aliases


def test_get_or_create_topic_raises_when_unresolvable(db_session):
    with patch("evidence_engine.topics.registry.resolve_to_mesh", return_value=None):
        try:
            get_or_create_topic(db_session, "not a real term")
            assert False, "expected ValueError"
        except ValueError:
            pass
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/topics/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.topics.registry'`

- [ ] **Step 7: Write `evidence_engine/topics/registry.py`**

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.db.models import Topic
from evidence_engine.topics.mesh import resolve_to_mesh


def get_or_create_topic(session: Session, free_text: str) -> Topic:
    resolution = resolve_to_mesh(free_text)
    if resolution is None:
        raise ValueError(f"Could not resolve '{free_text}' to a MeSH term")

    existing = session.execute(
        select(Topic).where(Topic.mesh_id == resolution.mesh_id)
    ).scalar_one_or_none()

    if existing:
        if free_text not in existing.aliases:
            existing.aliases = [*existing.aliases, free_text]
        return existing

    topic = Topic(
        mesh_id=resolution.mesh_id,
        canonical_label=resolution.canonical_label,
        aliases=[free_text],
        status="active",
    )
    session.add(topic)
    session.flush()
    return topic
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/topics/test_registry.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add evidence_engine/topics/ tests/topics/
git commit -m "feat: add MeSH topic normalization and topic registry"
```

---

## Task 5: RawPaper Shape, Adapter Base, and PubMed Adapter

**Files:**
- Create: `evidence_engine/adapters/__init__.py`
- Create: `evidence_engine/adapters/base.py`
- Create: `evidence_engine/adapters/pubmed.py`
- Create: `tests/fixtures/pubmed_efetch_sample.xml`
- Test: `tests/adapters/test_pubmed.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.Topic` (Task 2).
- Produces: `evidence_engine.adapters.base.RawPaper` (dataclass — fields: `source: str`, `pmid: str | None`, `doi: str | None`, `nct_id: str | None`, `semantic_scholar_id: str | None`, `title: str | None`, `abstract: str | None`, `authors: list[str]`, `journal: str | None`, `journal_issn: str | None`, `pub_date: date | None`, `publication_types: list[str]`, `citation_count: int | None`, `registered_sample_size: int | None`, `trial_status: str | None`, `raw_metadata: dict`). Produces `evidence_engine.adapters.base.SourceAdapter` (Protocol with `fetch_new(self, topic: Topic, since: datetime | None) -> list[RawPaper]`). Produces `evidence_engine.adapters.pubmed.PubMedAdapter` implementing that protocol — used by Task 8's dedup/merge and Task 18's orchestrator.

- [ ] **Step 1: Write `evidence_engine/adapters/base.py`**

```python
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from evidence_engine.db.models import Topic


@dataclass
class RawPaper:
    source: str
    pmid: str | None = None
    doi: str | None = None
    nct_id: str | None = None
    semantic_scholar_id: str | None = None
    title: str | None = None
    abstract: str | None = None
    authors: list[str] = field(default_factory=list)
    journal: str | None = None
    journal_issn: str | None = None
    pub_date: date | None = None
    publication_types: list[str] = field(default_factory=list)
    citation_count: int | None = None
    registered_sample_size: int | None = None
    trial_status: str | None = None
    raw_metadata: dict = field(default_factory=dict)


class SourceAdapter(Protocol):
    def fetch_new(self, topic: Topic, since: datetime | None) -> list[RawPaper]: ...
```

- [ ] **Step 2: Create a fixture EFetch XML response**

```xml
<!-- tests/fixtures/pubmed_efetch_sample.xml -->
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <Journal>
          <ISSN>0140-6736</ISSN>
          <Title>The Lancet</Title>
        </Journal>
        <ArticleTitle>Effect of Drug X on Outcome Y</ArticleTitle>
        <Abstract>
          <AbstractText>This randomized controlled trial examined...</AbstractText>
        </Abstract>
        <AuthorList>
          <Author><LastName>Smith</LastName><ForeName>Jane</ForeName></Author>
          <Author><LastName>Doe</LastName><ForeName>Alan</ForeName></Author>
        </AuthorList>
        <ELocationID EIdType="doi">10.1016/example.2024.001</ELocationID>
      </Article>
      <MedlineJournalInfo/>
    </MedlineCitation>
    <PubmedData>
      <History>
        <PubMedPubDate PubStatus="pubmed"><Year>2024</Year><Month>03</Month><Day>15</Day></PubMedPubDate>
      </History>
      <PublicationTypeList>
        <PublicationType>Randomized Controlled Trial</PublicationType>
      </PublicationTypeList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
```

- [ ] **Step 3: Write the failing test**

```python
# tests/adapters/test_pubmed.py
from datetime import date

import httpx
import respx

from evidence_engine.adapters.pubmed import PubMedAdapter
from evidence_engine.db.models import Topic

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


@respx.mock
def test_fetch_new_returns_parsed_raw_papers():
    respx.get(ESEARCH_URL).mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": ["12345678"]}})
    )
    with open("tests/fixtures/pubmed_efetch_sample.xml", "rb") as f:
        xml_body = f.read()
    respx.get(EFETCH_URL).mock(return_value=httpx.Response(200, content=xml_body))

    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    adapter = PubMedAdapter()
    papers = adapter.fetch_new(topic, since=None)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.source == "pubmed"
    assert paper.pmid == "12345678"
    assert paper.doi == "10.1016/example.2024.001"
    assert paper.title == "Effect of Drug X on Outcome Y"
    assert "Smith Jane" in paper.authors or "Jane Smith" in paper.authors
    assert paper.journal_issn == "0140-6736"
    assert paper.publication_types == ["Randomized Controlled Trial"]
    assert paper.pub_date == date(2024, 3, 15)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/adapters/test_pubmed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.adapters.pubmed'`

- [ ] **Step 5: Write `evidence_engine/adapters/pubmed.py`**

```python
from datetime import date, datetime

import httpx
from defusedxml import ElementTree
from tenacity import retry, stop_after_attempt, wait_exponential

from evidence_engine.adapters.base import RawPaper
from evidence_engine.config import get_settings
from evidence_engine.db.models import Topic

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


class PubMedAdapter:
    def _api_params(self) -> dict:
        settings = get_settings()
        return {"api_key": settings.ncbi_api_key} if settings.ncbi_api_key else {}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    def _search_ids(self, topic: Topic, since: datetime | None) -> list[str]:
        params = {
            "db": "pubmed",
            "term": f"{topic.canonical_label}[MeSH Terms]",
            "retmode": "json",
            "retmax": "500",
            **self._api_params(),
        }
        if since is not None:
            params["datetype"] = "pdat"
            params["mindate"] = since.strftime("%Y/%m/%d")
            params["maxdate"] = datetime.utcnow().strftime("%Y/%m/%d")

        with httpx.Client(timeout=15.0) as client:
            resp = client.get(ESEARCH_URL, params=params)
            resp.raise_for_status()
            return resp.json()["esearchresult"]["idlist"]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    def _fetch_records(self, pmids: list[str]) -> str:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                EFETCH_URL,
                params={
                    "db": "pubmed",
                    "id": ",".join(pmids),
                    "rettype": "abstract",
                    "retmode": "xml",
                    **self._api_params(),
                },
            )
            resp.raise_for_status()
            return resp.text

    def _parse_pub_date(self, article) -> date | None:
        pub_date_el = article.find(".//PubmedData/History/PubMedPubDate[@PubStatus='pubmed']")
        if pub_date_el is None:
            return None
        year = pub_date_el.findtext("Year")
        month = pub_date_el.findtext("Month")
        day = pub_date_el.findtext("Day")
        if not year:
            return None
        month_num = _MONTHS.get(month, None) if month and not month.isdigit() else (int(month) if month else 1)
        return date(int(year), month_num or 1, int(day) if day else 1)

    def _parse_article(self, article) -> RawPaper:
        pmid = article.findtext(".//MedlineCitation/PMID")
        title = article.findtext(".//ArticleTitle")
        abstract = article.findtext(".//Abstract/AbstractText")
        authors = []
        for author in article.findall(".//AuthorList/Author"):
            last = author.findtext("LastName") or ""
            first = author.findtext("ForeName") or ""
            name = f"{last} {first}".strip()
            if name:
                authors.append(name)
        journal = article.findtext(".//Journal/Title")
        issn = article.findtext(".//Journal/ISSN")
        doi = None
        for eloc in article.findall(".//ELocationID"):
            if eloc.get("EIdType") == "doi":
                doi = eloc.text
        pub_types = [
            pt.text for pt in article.findall(".//PublicationTypeList/PublicationType") if pt.text
        ]

        return RawPaper(
            source="pubmed",
            pmid=pmid,
            doi=doi,
            title=title,
            abstract=abstract,
            authors=authors,
            journal=journal,
            journal_issn=issn,
            pub_date=self._parse_pub_date(article),
            publication_types=pub_types,
            raw_metadata={},
        )

    def fetch_new(self, topic: Topic, since: datetime | None) -> list[RawPaper]:
        pmids = self._search_ids(topic, since)
        if not pmids:
            return []
        xml_text = self._fetch_records(pmids)
        root = ElementTree.fromstring(xml_text)
        return [self._parse_article(article) for article in root.findall(".//PubmedArticle")]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/adapters/test_pubmed.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add evidence_engine/adapters/ tests/adapters/test_pubmed.py tests/fixtures/pubmed_efetch_sample.xml
git commit -m "feat: add RawPaper shape, adapter protocol, and PubMed adapter"
```

---

## Task 6: Semantic Scholar Adapter

**Files:**
- Create: `evidence_engine/adapters/semantic_scholar.py`
- Test: `tests/adapters/test_semantic_scholar.py`

**Interfaces:**
- Consumes: `evidence_engine.adapters.base.RawPaper`, `SourceAdapter` (Task 5).
- Produces: `evidence_engine.adapters.semantic_scholar.SemanticScholarAdapter` implementing `SourceAdapter` — used by Task 8's dedup/merge and Task 18's orchestrator.

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_semantic_scholar.py
from datetime import date

import httpx
import respx

from evidence_engine.adapters.semantic_scholar import SemanticScholarAdapter
from evidence_engine.db.models import Topic

SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


@respx.mock
def test_fetch_new_returns_parsed_raw_papers():
    respx.get(SEARCH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "abc123",
                        "title": "Effect of Drug X on Outcome Y",
                        "abstract": "This randomized controlled trial...",
                        "publicationDate": "2024-03-15",
                        "citationCount": 42,
                        "influentialCitationCount": 5,
                        "journal": {"name": "The Lancet"},
                        "externalIds": {"DOI": "10.1016/example.2024.001", "PubMed": "12345678"},
                        "authors": [{"name": "Jane Smith"}, {"name": "Alan Doe"}],
                    }
                ]
            },
        )
    )

    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    adapter = SemanticScholarAdapter()
    papers = adapter.fetch_new(topic, since=None)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.source == "semantic_scholar"
    assert paper.semantic_scholar_id == "abc123"
    assert paper.doi == "10.1016/example.2024.001"
    assert paper.pmid == "12345678"
    assert paper.citation_count == 42
    assert paper.pub_date == date(2024, 3, 15)
    assert paper.authors == ["Jane Smith", "Alan Doe"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/adapters/test_semantic_scholar.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.adapters.semantic_scholar'`

- [ ] **Step 3: Write `evidence_engine/adapters/semantic_scholar.py`**

```python
from datetime import date, datetime

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from evidence_engine.adapters.base import RawPaper
from evidence_engine.config import get_settings
from evidence_engine.db.models import Topic

SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,abstract,publicationDate,citationCount,influentialCitationCount,journal,externalIds,authors"


class SemanticScholarAdapter:
    def _headers(self) -> dict:
        settings = get_settings()
        return {"x-api-key": settings.semantic_scholar_api_key} if settings.semantic_scholar_api_key else {}

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    def _search(self, query: str) -> list[dict]:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                SEARCH_URL,
                params={"query": query, "fields": FIELDS, "limit": 100},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json().get("data", [])

    def _parse_record(self, record: dict) -> RawPaper:
        external_ids = record.get("externalIds") or {}
        pub_date = None
        if record.get("publicationDate"):
            pub_date = datetime.strptime(record["publicationDate"], "%Y-%m-%d").date()

        return RawPaper(
            source="semantic_scholar",
            semantic_scholar_id=record.get("paperId"),
            doi=external_ids.get("DOI"),
            pmid=external_ids.get("PubMed"),
            title=record.get("title"),
            abstract=record.get("abstract"),
            authors=[a["name"] for a in record.get("authors", []) if a.get("name")],
            journal=(record.get("journal") or {}).get("name"),
            pub_date=pub_date,
            citation_count=record.get("citationCount"),
            raw_metadata={"influentialCitationCount": record.get("influentialCitationCount")},
        )

    def fetch_new(self, topic: Topic, since: datetime | None) -> list[RawPaper]:
        records = self._search(topic.canonical_label)
        papers = [self._parse_record(r) for r in records]
        if since is not None:
            papers = [p for p in papers if p.pub_date is None or p.pub_date >= since.date()]
        return papers
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/adapters/test_semantic_scholar.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evidence_engine/adapters/semantic_scholar.py tests/adapters/test_semantic_scholar.py
git commit -m "feat: add Semantic Scholar adapter"
```

---

## Task 7: ClinicalTrials.gov Adapter

**Files:**
- Create: `evidence_engine/adapters/clinicaltrials.py`
- Test: `tests/adapters/test_clinicaltrials.py`

**Interfaces:**
- Consumes: `evidence_engine.adapters.base.RawPaper`, `SourceAdapter` (Task 5).
- Produces: `evidence_engine.adapters.clinicaltrials.ClinicalTrialsAdapter` implementing `SourceAdapter` — used by Task 8's dedup/merge, Task 18's orchestrator, and Task 12's outcome-switching risk-of-bias check.

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_clinicaltrials.py
import httpx
import respx

from evidence_engine.adapters.clinicaltrials import ClinicalTrialsAdapter
from evidence_engine.db.models import Topic

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"


@respx.mock
def test_fetch_new_returns_parsed_raw_papers():
    respx.get(STUDIES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "studies": [
                    {
                        "protocolSection": {
                            "identificationModule": {
                                "nctId": "NCT01234567",
                                "briefTitle": "Trial of Drug X for Outcome Y",
                            },
                            "statusModule": {"overallStatus": "COMPLETED"},
                            "designModule": {"enrollmentInfo": {"count": 300}},
                        }
                    }
                ]
            },
        )
    )

    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    adapter = ClinicalTrialsAdapter()
    papers = adapter.fetch_new(topic, since=None)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.source == "clinicaltrials"
    assert paper.nct_id == "NCT01234567"
    assert paper.title == "Trial of Drug X for Outcome Y"
    assert paper.trial_status == "COMPLETED"
    assert paper.registered_sample_size == 300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/adapters/test_clinicaltrials.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.adapters.clinicaltrials'`

- [ ] **Step 3: Write `evidence_engine/adapters/clinicaltrials.py`**

```python
from datetime import datetime

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from evidence_engine.adapters.base import RawPaper
from evidence_engine.db.models import Topic

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"


class ClinicalTrialsAdapter:
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
    def _search(self, query: str) -> list[dict]:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(STUDIES_URL, params={"query.term": query, "pageSize": 100})
            resp.raise_for_status()
            return resp.json().get("studies", [])

    def _parse_study(self, study: dict) -> RawPaper:
        protocol = study.get("protocolSection", {})
        identification = protocol.get("identificationModule", {})
        status = protocol.get("statusModule", {})
        design = protocol.get("designModule", {})
        enrollment = design.get("enrollmentInfo", {})

        return RawPaper(
            source="clinicaltrials",
            nct_id=identification.get("nctId"),
            title=identification.get("briefTitle"),
            trial_status=status.get("overallStatus"),
            registered_sample_size=enrollment.get("count"),
            raw_metadata=study,
        )

    def fetch_new(self, topic: Topic, since: datetime | None) -> list[RawPaper]:
        studies = self._search(topic.canonical_label)
        return [self._parse_study(s) for s in studies]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/adapters/test_clinicaltrials.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evidence_engine/adapters/clinicaltrials.py tests/adapters/test_clinicaltrials.py
git commit -m "feat: add ClinicalTrials.gov adapter"
```

---

## Task 8: Cross-Source Deduplication, Merge, and Upsert

**Files:**
- Create: `evidence_engine/adapters/merge.py`
- Test: `tests/adapters/test_merge.py`

**Interfaces:**
- Consumes: `evidence_engine.adapters.base.RawPaper` (Task 5), `evidence_engine.db.models.Paper`, `PaperTopic`, `Topic` (Task 2).
- Produces: `evidence_engine.adapters.merge.merge_raw_papers(raw_papers: list[RawPaper]) -> list[RawPaper]` (groups and merges by DOI, then PMID). Produces `evidence_engine.adapters.merge.upsert_paper(session: Session, topic: Topic, raw_paper: RawPaper) -> Paper` — used by Task 18's orchestrator.

- [ ] **Step 1: Write the failing test for merging**

```python
# tests/adapters/test_merge.py
from evidence_engine.adapters.base import RawPaper
from evidence_engine.adapters.merge import merge_raw_papers, upsert_paper
from evidence_engine.db.models import Paper, Topic


def test_merge_raw_papers_combines_matching_doi():
    pubmed_paper = RawPaper(
        source="pubmed",
        pmid="12345678",
        doi="10.1016/example.2024.001",
        title="Effect of Drug X",
        abstract="Background...",
        publication_types=["Randomized Controlled Trial"],
    )
    s2_paper = RawPaper(
        source="semantic_scholar",
        doi="10.1016/example.2024.001",
        semantic_scholar_id="abc123",
        citation_count=42,
    )

    merged = merge_raw_papers([pubmed_paper, s2_paper])

    assert len(merged) == 1
    combined = merged[0]
    assert combined.pmid == "12345678"
    assert combined.semantic_scholar_id == "abc123"
    assert combined.citation_count == 42
    assert combined.publication_types == ["Randomized Controlled Trial"]


def test_merge_raw_papers_keeps_distinct_papers_separate():
    paper_a = RawPaper(source="pubmed", doi="10.1/aaa", title="Paper A")
    paper_b = RawPaper(source="pubmed", doi="10.1/bbb", title="Paper B")

    merged = merge_raw_papers([paper_a, paper_b])

    assert len(merged) == 2


def test_upsert_paper_creates_new_paper_and_links_topic(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    raw_paper = RawPaper(source="pubmed", pmid="12345678", doi="10.1/xyz", title="Effect of Drug X")
    paper = upsert_paper(db_session, topic, raw_paper)
    db_session.flush()

    assert paper.pmid == "12345678"
    fetched = db_session.query(Paper).filter_by(pmid="12345678").one()
    assert fetched.id == paper.id


def test_upsert_paper_updates_existing_paper_on_second_call(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    first = upsert_paper(db_session, topic, RawPaper(source="pubmed", pmid="12345678", title="Draft Title"))
    db_session.flush()

    second = upsert_paper(
        db_session, topic, RawPaper(source="semantic_scholar", pmid="12345678", citation_count=10)
    )
    db_session.flush()

    assert second.id == first.id
    assert db_session.query(Paper).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/adapters/test_merge.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.adapters.merge'`

- [ ] **Step 3: Write `evidence_engine/adapters/merge.py`**

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.adapters.base import RawPaper
from evidence_engine.db.models import Paper, PaperTopic, Topic


def _merge_two(a: RawPaper, b: RawPaper) -> RawPaper:
    merged_fields = {}
    for f in a.__dataclass_fields__:
        a_val = getattr(a, f)
        b_val = getattr(b, f)
        if isinstance(a_val, list):
            merged_fields[f] = a_val or b_val
        elif isinstance(a_val, dict):
            merged_fields[f] = {**b_val, **a_val} if a_val else b_val
        else:
            merged_fields[f] = a_val if a_val is not None else b_val
    merged_fields["source"] = f"{a.source}+{b.source}"
    return RawPaper(**merged_fields)


def merge_raw_papers(raw_papers: list[RawPaper]) -> list[RawPaper]:
    groups: list[RawPaper] = []
    for raw_paper in raw_papers:
        match_index = None
        for i, existing in enumerate(groups):
            same_doi = raw_paper.doi and existing.doi and raw_paper.doi == existing.doi
            same_pmid = raw_paper.pmid and existing.pmid and raw_paper.pmid == existing.pmid
            if same_doi or same_pmid:
                match_index = i
                break
        if match_index is None:
            groups.append(raw_paper)
        else:
            groups[match_index] = _merge_two(groups[match_index], raw_paper)
    return groups


def upsert_paper(session: Session, topic: Topic, raw_paper: RawPaper) -> Paper:
    existing = None
    if raw_paper.doi:
        existing = session.execute(select(Paper).where(Paper.doi == raw_paper.doi)).scalar_one_or_none()
    if existing is None and raw_paper.pmid:
        existing = session.execute(select(Paper).where(Paper.pmid == raw_paper.pmid)).scalar_one_or_none()
    if existing is None and raw_paper.nct_id:
        existing = session.execute(select(Paper).where(Paper.nct_id == raw_paper.nct_id)).scalar_one_or_none()

    if existing:
        paper = existing
        paper.pmid = paper.pmid or raw_paper.pmid
        paper.doi = paper.doi or raw_paper.doi
        paper.nct_id = paper.nct_id or raw_paper.nct_id
        paper.semantic_scholar_id = paper.semantic_scholar_id or raw_paper.semantic_scholar_id
        paper.title = paper.title or raw_paper.title
        paper.abstract = paper.abstract or raw_paper.abstract
        paper.authors = paper.authors or raw_paper.authors
        paper.journal = paper.journal or raw_paper.journal
        paper.journal_issn = paper.journal_issn or raw_paper.journal_issn
        paper.pub_date = paper.pub_date or raw_paper.pub_date
        paper.publication_types = paper.publication_types or raw_paper.publication_types
    else:
        paper = Paper(
            pmid=raw_paper.pmid,
            doi=raw_paper.doi,
            nct_id=raw_paper.nct_id,
            semantic_scholar_id=raw_paper.semantic_scholar_id,
            title=raw_paper.title or "",
            abstract=raw_paper.abstract,
            authors=raw_paper.authors,
            journal=raw_paper.journal,
            journal_issn=raw_paper.journal_issn,
            pub_date=raw_paper.pub_date,
            publication_types=raw_paper.publication_types,
            raw_metadata=raw_paper.raw_metadata,
        )
        session.add(paper)
        session.flush()

    link_exists = session.execute(
        select(PaperTopic).where(PaperTopic.paper_id == paper.id, PaperTopic.topic_id == topic.id)
    ).scalar_one_or_none()
    if not link_exists:
        session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))

    return paper
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/adapters/test_merge.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evidence_engine/adapters/merge.py tests/adapters/test_merge.py
git commit -m "feat: add cross-source deduplication, merge, and upsert"
```

---

## Task 9: Anthropic Client and Study-Type Classification

**Files:**
- Create: `evidence_engine/llm/__init__.py`
- Create: `evidence_engine/llm/client.py`
- Create: `evidence_engine/scoring/__init__.py`
- Create: `evidence_engine/scoring/classifier.py`
- Test: `tests/scoring/test_classifier.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.Paper`, `StudyType` (Task 2), `evidence_engine.config.get_settings` (Task 1).
- Produces: `evidence_engine.llm.client.get_anthropic_client() -> Anthropic` — reused by Tasks 10, 12, 14, 15. Produces `evidence_engine.scoring.classifier.classify_study_type(paper: Paper) -> StudyType` — used by Task 13.

- [ ] **Step 1: Write `evidence_engine/llm/client.py`**

```python
from anthropic import Anthropic

from evidence_engine.config import get_settings


def get_anthropic_client() -> Anthropic:
    return Anthropic(api_key=get_settings().anthropic_api_key)
```

- [ ] **Step 2: Write the failing test for classification**

```python
# tests/scoring/test_classifier.py
import httpx
import respx

from evidence_engine.db.models import Paper, StudyType
from evidence_engine.scoring.classifier import classify_study_type

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def test_classify_study_type_trusts_pubmed_tag():
    paper = Paper(title="A trial", abstract="...", publication_types=["Randomized Controlled Trial"])
    assert classify_study_type(paper) == StudyType.RCT


@respx.mock
def test_classify_study_type_falls_back_to_llm_when_tag_missing():
    respx.post(MESSAGES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "classify_study",
                        "input": {"study_type": "cohort"},
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 50, "output_tokens": 10},
            },
        )
    )

    paper = Paper(title="A study", abstract="We followed 500 patients over five years...", publication_types=[])
    assert classify_study_type(paper) == StudyType.COHORT


def test_classify_study_type_returns_unknown_without_abstract():
    paper = Paper(title="A study", abstract=None, publication_types=[])
    assert classify_study_type(paper) == StudyType.UNKNOWN
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/scoring/test_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.scoring.classifier'`

- [ ] **Step 4: Write `evidence_engine/scoring/classifier.py`**

```python
from evidence_engine.config import get_settings
from evidence_engine.db.models import Paper, StudyType
from evidence_engine.llm.client import get_anthropic_client

PUBLICATION_TYPE_MAP = {
    "Meta-Analysis": StudyType.META_ANALYSIS,
    "Systematic Review": StudyType.SYSTEMATIC_REVIEW,
    "Randomized Controlled Trial": StudyType.RCT,
    "Case Reports": StudyType.CASE_SERIES,
    "Editorial": StudyType.OPINION_EDITORIAL,
    "Comment": StudyType.OPINION_EDITORIAL,
}

CLASSIFY_TOOL = {
    "name": "classify_study",
    "description": "Classify the study type of a biomedical paper based on its title and abstract.",
    "input_schema": {
        "type": "object",
        "properties": {
            "study_type": {
                "type": "string",
                "enum": [t.value for t in StudyType if t != StudyType.UNKNOWN],
            }
        },
        "required": ["study_type"],
    },
}


def classify_study_type(paper: Paper) -> StudyType:
    for pub_type in paper.publication_types:
        if pub_type in PUBLICATION_TYPE_MAP:
            return PUBLICATION_TYPE_MAP[pub_type]

    if not paper.abstract:
        return StudyType.UNKNOWN

    client = get_anthropic_client()
    response = client.messages.create(
        model=get_settings().anthropic_model,
        max_tokens=100,
        tools=[CLASSIFY_TOOL],
        tool_choice={"type": "tool", "name": "classify_study"},
        messages=[
            {
                "role": "user",
                "content": f"Title: {paper.title}\n\nAbstract: {paper.abstract}",
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use" and block.input.get("study_type"):
            return StudyType(block.input["study_type"])
    return StudyType.UNKNOWN
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/scoring/test_classifier.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add evidence_engine/llm/ evidence_engine/scoring/__init__.py evidence_engine/scoring/classifier.py tests/scoring/test_classifier.py
git commit -m "feat: add Anthropic client and study-type classification"
```

---

## Task 10: Sample Size Extraction

**Files:**
- Create: `evidence_engine/scoring/sample_size.py`
- Test: `tests/scoring/test_sample_size.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.Paper` (Task 2), `evidence_engine.llm.client.get_anthropic_client` (Task 9).
- Produces: `evidence_engine.scoring.sample_size.extract_sample_size(paper: Paper) -> int | None` — used by Task 13.

- [ ] **Step 1: Write the failing test**

```python
# tests/scoring/test_sample_size.py
import httpx
import respx

from evidence_engine.db.models import Paper
from evidence_engine.scoring.sample_size import extract_sample_size

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def _mock_response(reported: bool, size: int | None):
    return httpx.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-6",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "extract_sample_size",
                    "input": {"sample_size_reported": reported, "sample_size": size},
                }
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 50, "output_tokens": 10},
        },
    )


@respx.mock
def test_extract_sample_size_returns_reported_value():
    respx.post(MESSAGES_URL).mock(return_value=_mock_response(True, 245))
    paper = Paper(title="A trial", abstract="We enrolled 245 patients...")
    assert extract_sample_size(paper) == 245


@respx.mock
def test_extract_sample_size_returns_none_when_not_reported():
    respx.post(MESSAGES_URL).mock(return_value=_mock_response(False, None))
    paper = Paper(title="An opinion piece", abstract="In this commentary we argue...")
    assert extract_sample_size(paper) is None


def test_extract_sample_size_returns_none_without_abstract():
    paper = Paper(title="A trial", abstract=None)
    assert extract_sample_size(paper) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/scoring/test_sample_size.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.scoring.sample_size'`

- [ ] **Step 3: Write `evidence_engine/scoring/sample_size.py`**

```python
from evidence_engine.config import get_settings
from evidence_engine.db.models import Paper
from evidence_engine.llm.client import get_anthropic_client

EXTRACT_TOOL = {
    "name": "extract_sample_size",
    "description": "Extract the study's reported sample size (number of participants/subjects) from its abstract.",
    "input_schema": {
        "type": "object",
        "properties": {
            "sample_size_reported": {"type": "boolean"},
            "sample_size": {"type": ["integer", "null"]},
        },
        "required": ["sample_size_reported", "sample_size"],
    },
}


def extract_sample_size(paper: Paper) -> int | None:
    if not paper.abstract:
        return None

    client = get_anthropic_client()
    response = client.messages.create(
        model=get_settings().anthropic_model,
        max_tokens=100,
        tools=[EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "extract_sample_size"},
        messages=[
            {
                "role": "user",
                "content": f"Title: {paper.title}\n\nAbstract: {paper.abstract}",
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use":
            if block.input.get("sample_size_reported"):
                return block.input.get("sample_size")
            return None
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/scoring/test_sample_size.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evidence_engine/scoring/sample_size.py tests/scoring/test_sample_size.py
git commit -m "feat: add LLM-based sample size extraction"
```

---

## Task 11: Deterministic Base Score Formula

**Files:**
- Create: `evidence_engine/scoring/formula.py`
- Test: `tests/scoring/test_formula.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.StudyType` (Task 2).
- Produces: `evidence_engine.scoring.formula.compute_base_score(study_type: StudyType, sample_size: int | None, citation_count: int, journal_sjr: float | None) -> float` (0-100) — used by Task 13.

- [ ] **Step 1: Write the failing test**

```python
# tests/scoring/test_formula.py
import pytest

from evidence_engine.db.models import StudyType
from evidence_engine.scoring.formula import compute_base_score


def test_meta_analysis_with_strong_signals_scores_high():
    score = compute_base_score(
        study_type=StudyType.META_ANALYSIS,
        sample_size=1000,
        citation_count=50,
        journal_sjr=5.0,
    )
    assert score == pytest.approx(84.5, abs=0.1)


def test_opinion_editorial_with_no_signals_scores_low():
    score = compute_base_score(
        study_type=StudyType.OPINION_EDITORIAL,
        sample_size=None,
        citation_count=0,
        journal_sjr=None,
    )
    assert score == pytest.approx(5.5, abs=0.1)


def test_higher_study_tier_always_scores_higher_given_equal_signals():
    rct_score = compute_base_score(StudyType.RCT, 200, 10, 2.0)
    case_series_score = compute_base_score(StudyType.CASE_SERIES, 200, 10, 2.0)
    assert rct_score > case_series_score
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/scoring/test_formula.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.scoring.formula'`

- [ ] **Step 3: Write `evidence_engine/scoring/formula.py`**

```python
import math

from evidence_engine.db.models import StudyType

STUDY_TYPE_TIER_SCORES: dict[StudyType, float] = {
    StudyType.META_ANALYSIS: 100.0,
    StudyType.SYSTEMATIC_REVIEW: 95.0,
    StudyType.RCT: 80.0,
    StudyType.COHORT: 60.0,
    StudyType.CASE_CONTROL: 50.0,
    StudyType.CASE_SERIES: 30.0,
    StudyType.OPINION_EDITORIAL: 10.0,
    StudyType.UNKNOWN: 20.0,
}

WEIGHTS = {"study_type": 0.55, "sample_size": 0.15, "citations": 0.15, "journal": 0.15}


def _sample_size_score(sample_size: int | None) -> float:
    if not sample_size or sample_size <= 0:
        return 0.0
    return min(100.0, math.log10(sample_size + 1) * 40)


def _citation_score(citation_count: int) -> float:
    if citation_count <= 0:
        return 0.0
    return min(100.0, math.log10(citation_count + 1) * 33)


def _journal_score(journal_sjr: float | None) -> float:
    if not journal_sjr or journal_sjr <= 0:
        return 0.0
    return min(100.0, journal_sjr * 8)


def compute_base_score(
    study_type: StudyType,
    sample_size: int | None,
    citation_count: int,
    journal_sjr: float | None,
) -> float:
    total = (
        WEIGHTS["study_type"] * STUDY_TYPE_TIER_SCORES.get(study_type, 20.0)
        + WEIGHTS["sample_size"] * _sample_size_score(sample_size)
        + WEIGHTS["citations"] * _citation_score(citation_count)
        + WEIGHTS["journal"] * _journal_score(journal_sjr)
    )
    return round(total, 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/scoring/test_formula.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evidence_engine/scoring/formula.py tests/scoring/test_formula.py
git commit -m "feat: add GRADE-inspired deterministic base score formula"
```

---

## Task 12: LLM Risk-of-Bias Detection and Quality Breakdown

**Files:**
- Create: `evidence_engine/scoring/risk_of_bias.py`
- Test: `tests/scoring/test_risk_of_bias.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.Paper` (Task 2), `evidence_engine.llm.client.get_anthropic_client` (Task 9).
- Produces: `evidence_engine.scoring.risk_of_bias.RiskOfBiasResult` (dataclass: `flags: list[str]`, `quality_breakdown: str`, `penalty: float`) and `evidence_engine.scoring.risk_of_bias.detect_risk_of_bias(paper: Paper) -> RiskOfBiasResult` — used by Task 13.

- [ ] **Step 1: Write the failing test**

```python
# tests/scoring/test_risk_of_bias.py
import httpx
import respx

from evidence_engine.db.models import Paper
from evidence_engine.scoring.risk_of_bias import detect_risk_of_bias

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


@respx.mock
def test_detect_risk_of_bias_applies_penalty_for_flags():
    respx.post(MESSAGES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "assess_risk_of_bias",
                        "input": {
                            "flags": ["no_blinding", "underpowered_sample"],
                            "quality_breakdown": "Small, unblinded trial; results directionally consistent with prior work.",
                        },
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 50, "output_tokens": 10},
            },
        )
    )

    paper = Paper(title="A trial", abstract="We conducted an open-label trial of 20 patients...")
    result = detect_risk_of_bias(paper)

    assert result.flags == ["no_blinding", "underpowered_sample"]
    assert "unblinded" in result.quality_breakdown
    assert result.penalty == 25.0


def test_detect_risk_of_bias_returns_no_flags_without_abstract():
    paper = Paper(title="A trial", abstract=None)
    result = detect_risk_of_bias(paper)
    assert result.flags == []
    assert result.penalty == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/scoring/test_risk_of_bias.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.scoring.risk_of_bias'`

- [ ] **Step 3: Write `evidence_engine/scoring/risk_of_bias.py`**

```python
from dataclasses import dataclass

from evidence_engine.config import get_settings
from evidence_engine.db.models import Paper
from evidence_engine.llm.client import get_anthropic_client

FLAG_PENALTIES = {
    "no_control_group": 15.0,
    "no_blinding": 10.0,
    "funding_conflict_of_interest": 10.0,
    "underpowered_sample": 15.0,
    "outcome_switching": 20.0,
    "other": 5.0,
}
MAX_PENALTY = 50.0

ASSESS_TOOL = {
    "name": "assess_risk_of_bias",
    "description": "Identify concrete risk-of-bias issues in a biomedical paper from its abstract, and write a short quality critique.",
    "input_schema": {
        "type": "object",
        "properties": {
            "flags": {
                "type": "array",
                "items": {"type": "string", "enum": list(FLAG_PENALTIES.keys())},
            },
            "quality_breakdown": {"type": "string"},
        },
        "required": ["flags", "quality_breakdown"],
    },
}


@dataclass
class RiskOfBiasResult:
    flags: list[str]
    quality_breakdown: str
    penalty: float


def detect_risk_of_bias(paper: Paper) -> RiskOfBiasResult:
    if not paper.abstract:
        return RiskOfBiasResult(flags=[], quality_breakdown="", penalty=0.0)

    client = get_anthropic_client()
    response = client.messages.create(
        model=get_settings().anthropic_model,
        max_tokens=500,
        tools=[ASSESS_TOOL],
        tool_choice={"type": "tool", "name": "assess_risk_of_bias"},
        messages=[
            {
                "role": "user",
                "content": f"Title: {paper.title}\n\nAbstract: {paper.abstract}",
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use":
            flags = block.input.get("flags", [])
            penalty = min(MAX_PENALTY, sum(FLAG_PENALTIES.get(f, 0.0) for f in flags))
            return RiskOfBiasResult(
                flags=flags,
                quality_breakdown=block.input.get("quality_breakdown", ""),
                penalty=penalty,
            )
    return RiskOfBiasResult(flags=[], quality_breakdown="", penalty=0.0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/scoring/test_risk_of_bias.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evidence_engine/scoring/risk_of_bias.py tests/scoring/test_risk_of_bias.py
git commit -m "feat: add LLM risk-of-bias detection and quality breakdown"
```

---

## Task 13: Score Assembly and Evidence Tier Assignment

**Files:**
- Create: `evidence_engine/scoring/assemble.py`
- Test: `tests/scoring/test_assemble.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.Paper`, `Score`, `EvidenceTier`, `StudyType`, `JournalSJR` (Task 2/3), `classify_study_type` (Task 9), `extract_sample_size` (Task 10), `compute_base_score` (Task 11), `detect_risk_of_bias` (Task 12).
- Produces: `evidence_engine.scoring.assemble.assign_evidence_tier(final_score: float, study_type: StudyType) -> EvidenceTier` and `evidence_engine.scoring.assemble.score_paper(session: Session, paper: Paper, citation_count: int, model_version: str) -> Score` — used by Task 18's orchestrator.

- [ ] **Step 1: Write the failing test**

```python
# tests/scoring/test_assemble.py
from unittest.mock import patch

from evidence_engine.db.models import EvidenceTier, JournalSJR, Paper, Score, StudyType
from evidence_engine.scoring.assemble import assign_evidence_tier, score_paper
from evidence_engine.scoring.risk_of_bias import RiskOfBiasResult


def test_assign_evidence_tier_established_requires_top_tier_study_and_high_score():
    assert assign_evidence_tier(85.0, StudyType.META_ANALYSIS) == EvidenceTier.ESTABLISHED
    assert assign_evidence_tier(85.0, StudyType.RCT) == EvidenceTier.EMERGING
    assert assign_evidence_tier(40.0, StudyType.META_ANALYSIS) == EvidenceTier.SPECULATIVE


def test_score_paper_persists_score_with_all_components(db_session):
    journal_sjr = JournalSJR(issn="0140-6736", journal_name="The Lancet", sjr_score=5.0, year=2024)
    db_session.add(journal_sjr)
    paper = Paper(
        title="A meta-analysis",
        abstract="We pooled 20 trials...",
        journal_issn="0140-6736",
        publication_types=["Meta-Analysis"],
    )
    db_session.add(paper)
    db_session.flush()

    with (
        patch("evidence_engine.scoring.assemble.extract_sample_size", return_value=1000),
        patch(
            "evidence_engine.scoring.assemble.detect_risk_of_bias",
            return_value=RiskOfBiasResult(flags=["no_blinding"], quality_breakdown="Some limitations.", penalty=10.0),
        ),
    ):
        score = score_paper(db_session, paper, citation_count=50, model_version="v1")
    db_session.flush()

    assert score.paper_id == paper.id
    assert score.study_type == StudyType.META_ANALYSIS
    assert score.sample_size == 1000
    assert score.citation_count == 50
    assert score.journal_sjr == 5.0
    assert score.risk_of_bias_flags == ["no_blinding"]
    assert score.final_score == score.base_score - 10.0
    assert score.model_version == "v1"

    fetched = db_session.query(Score).filter_by(paper_id=paper.id).one()
    assert fetched.id == score.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/scoring/test_assemble.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.scoring.assemble'`

- [ ] **Step 3: Write `evidence_engine/scoring/assemble.py`**

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.db.models import EvidenceTier, JournalSJR, Paper, Score, StudyType
from evidence_engine.scoring.classifier import classify_study_type
from evidence_engine.scoring.formula import compute_base_score
from evidence_engine.scoring.risk_of_bias import detect_risk_of_bias
from evidence_engine.scoring.sample_size import extract_sample_size

TOP_TIER_TYPES = {StudyType.META_ANALYSIS, StudyType.SYSTEMATIC_REVIEW}


def assign_evidence_tier(final_score: float, study_type: StudyType) -> EvidenceTier:
    if study_type in TOP_TIER_TYPES and final_score >= 70.0:
        return EvidenceTier.ESTABLISHED
    if final_score >= 50.0:
        return EvidenceTier.EMERGING
    return EvidenceTier.SPECULATIVE


def _latest_sjr(session: Session, journal_issn: str | None) -> float | None:
    if not journal_issn:
        return None
    row = (
        session.execute(
            select(JournalSJR).where(JournalSJR.issn == journal_issn).order_by(JournalSJR.year.desc())
        )
        .scalars()
        .first()
    )
    return row.sjr_score if row else None


def score_paper(session: Session, paper: Paper, citation_count: int, model_version: str) -> Score:
    study_type = classify_study_type(paper)
    sample_size = extract_sample_size(paper)
    journal_sjr = _latest_sjr(session, paper.journal_issn)
    base_score = compute_base_score(study_type, sample_size, citation_count, journal_sjr)
    risk_result = detect_risk_of_bias(paper)
    final_score = max(0.0, base_score - risk_result.penalty)
    tier = assign_evidence_tier(final_score, study_type)

    existing = session.execute(select(Score).where(Score.paper_id == paper.id)).scalar_one_or_none()
    score = existing or Score(paper_id=paper.id)
    score.study_type = study_type
    score.sample_size = sample_size
    score.citation_count = citation_count
    score.journal_sjr = journal_sjr
    score.base_score = base_score
    score.risk_of_bias_flags = risk_result.flags
    score.final_score = final_score
    score.evidence_tier = tier
    score.quality_breakdown = risk_result.quality_breakdown
    score.model_version = model_version

    if not existing:
        session.add(score)
    session.flush()
    return score
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/scoring/test_assemble.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evidence_engine/scoring/assemble.py tests/scoring/test_assemble.py
git commit -m "feat: add score assembly and evidence tier assignment"
```

---

## Task 14: Top-Tier Evidence Retrieval and Consensus Synthesis

**Files:**
- Create: `evidence_engine/consensus/__init__.py`
- Create: `evidence_engine/consensus/synthesizer.py`
- Test: `tests/consensus/test_synthesizer.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.Score`, `Paper`, `PaperTopic`, `Topic`, `ConsensusSnapshot`, `StudyType` (Task 2), `evidence_engine.llm.client.get_anthropic_client` (Task 9).
- Produces: `evidence_engine.consensus.synthesizer.get_top_tier_scores(session: Session, topic: Topic) -> list[Score]` and `evidence_engine.consensus.synthesizer.synthesize_consensus(session: Session, topic: Topic, model_version: str) -> ConsensusSnapshot` — used by Task 15 and Task 18's orchestrator.

- [ ] **Step 1: Write the failing test**

```python
# tests/consensus/test_synthesizer.py
import httpx
import respx

from evidence_engine.consensus.synthesizer import get_top_tier_scores, synthesize_consensus
from evidence_engine.db.models import ConsensusSnapshot, Paper, PaperTopic, Score, StudyType, Topic

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def _link(session, topic, title, abstract, study_type, final_score=90.0):
    paper = Paper(title=title, abstract=abstract)
    session.add(paper)
    session.flush()
    session.add(PaperTopic(paper_id=paper.id, topic_id=topic.id))
    score = Score(paper_id=paper.id, study_type=study_type, final_score=final_score, model_version="v1")
    session.add(score)
    session.flush()
    return paper, score


def test_get_top_tier_scores_filters_to_meta_analyses_and_systematic_reviews(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    _link(db_session, topic, "Meta-analysis A", "abstract", StudyType.META_ANALYSIS)
    _link(db_session, topic, "Case series B", "abstract", StudyType.CASE_SERIES)

    top_tier = get_top_tier_scores(db_session, topic)

    assert len(top_tier) == 1
    assert top_tier[0].study_type == StudyType.META_ANALYSIS


@respx.mock
def test_synthesize_consensus_grounds_text_in_top_tier_papers(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    _link(db_session, topic, "Meta-analysis A", "Pooled 10 trials, n=5000...", StudyType.META_ANALYSIS)
    paper_b, _ = _link(db_session, topic, "Systematic review B", "Reviewed 8 RCTs...", StudyType.SYSTEMATIC_REVIEW)

    respx.post(MESSAGES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "synthesize_consensus",
                        "input": {
                            "consensus_text": "Across pooled trials, treatment reduces risk.",
                            "supporting_indices": [1],
                        },
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        )
    )

    snapshot = synthesize_consensus(db_session, topic, model_version="v1")

    assert snapshot.is_insufficient_evidence is False
    assert "reduces risk" in snapshot.consensus_text
    assert snapshot.supporting_paper_ids == [paper_b.id]


def test_synthesize_consensus_flags_insufficient_evidence_below_threshold(db_session):
    topic = Topic(canonical_label="Rare Condition", mesh_id="D000000")
    db_session.add(topic)
    db_session.flush()

    _link(db_session, topic, "Meta-analysis A", "abstract", StudyType.META_ANALYSIS)

    snapshot = synthesize_consensus(db_session, topic, model_version="v1")

    assert snapshot.is_insufficient_evidence is True
    assert snapshot.consensus_text is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/consensus/test_synthesizer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.consensus.synthesizer'`

- [ ] **Step 3: Write `evidence_engine/consensus/synthesizer.py`**

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.config import get_settings
from evidence_engine.db.models import ConsensusSnapshot, Paper, PaperTopic, Score, StudyType, Topic
from evidence_engine.llm.client import get_anthropic_client

TOP_TIER_TYPES = {StudyType.META_ANALYSIS, StudyType.SYSTEMATIC_REVIEW}
MIN_TOP_TIER_PAPERS = 2

SYNTHESIZE_TOOL = {
    "name": "synthesize_consensus",
    "description": "Write a consensus paragraph for a biomedical topic grounded only in the provided top-tier papers.",
    "input_schema": {
        "type": "object",
        "properties": {
            "consensus_text": {"type": "string"},
            "supporting_indices": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["consensus_text", "supporting_indices"],
    },
}


def _is_top_tier(score: Score) -> bool:
    return score.study_type in TOP_TIER_TYPES or (score.study_type == StudyType.RCT and score.final_score >= 70.0)


def get_top_tier_scores(session: Session, topic: Topic) -> list[Score]:
    rows = (
        session.execute(
            select(Score)
            .join(Paper, Score.paper_id == Paper.id)
            .join(PaperTopic, PaperTopic.paper_id == Paper.id)
            .where(PaperTopic.topic_id == topic.id, Paper.is_retracted.is_(False))
        )
        .scalars()
        .all()
    )
    return [s for s in rows if _is_top_tier(s)]


def synthesize_consensus(session: Session, topic: Topic, model_version: str) -> ConsensusSnapshot:
    top_tier = get_top_tier_scores(session, topic)

    if len(top_tier) < MIN_TOP_TIER_PAPERS:
        snapshot = ConsensusSnapshot(
            topic_id=topic.id,
            consensus_text=None,
            is_insufficient_evidence=True,
            supporting_paper_ids=[],
            model_version=model_version,
        )
        session.add(snapshot)
        session.flush()
        return snapshot

    listing = "\n\n".join(
        f"[{i}] {s.paper.title}\nAbstract: {s.paper.abstract}" for i, s in enumerate(top_tier)
    )
    client = get_anthropic_client()
    response = client.messages.create(
        model=get_settings().anthropic_model,
        max_tokens=1000,
        tools=[SYNTHESIZE_TOOL],
        tool_choice={"type": "tool", "name": "synthesize_consensus"},
        messages=[
            {"role": "user", "content": f"Topic: {topic.canonical_label}\n\nPapers:\n{listing}"}
        ],
    )

    consensus_text = None
    supporting_ids = []
    for block in response.content:
        if block.type == "tool_use":
            consensus_text = block.input.get("consensus_text")
            indices = block.input.get("supporting_indices", [])
            supporting_ids = [top_tier[i].paper_id for i in indices if 0 <= i < len(top_tier)]

    snapshot = ConsensusSnapshot(
        topic_id=topic.id,
        consensus_text=consensus_text,
        is_insufficient_evidence=False,
        supporting_paper_ids=supporting_ids,
        model_version=model_version,
    )
    session.add(snapshot)
    session.flush()
    return snapshot
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/consensus/test_synthesizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evidence_engine/consensus/ tests/consensus/test_synthesizer.py
git commit -m "feat: add top-tier evidence retrieval and consensus synthesis"
```

---

## Task 15: Contradiction Detection

**Files:**
- Create: `evidence_engine/consensus/contradiction.py`
- Test: `tests/consensus/test_contradiction.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.Paper`, `ConsensusSnapshot` (Task 2), `evidence_engine.llm.client.get_anthropic_client` (Task 9).
- Produces: `evidence_engine.consensus.contradiction.ContradictionResult` (dataclass: `contradicts: bool`, `note: str | None`) and `evidence_engine.consensus.contradiction.detect_contradiction(paper: Paper, consensus: ConsensusSnapshot) -> ContradictionResult` — used by Task 18's orchestrator.

- [ ] **Step 1: Write the failing test**

```python
# tests/consensus/test_contradiction.py
import httpx
import respx

from evidence_engine.consensus.contradiction import detect_contradiction
from evidence_engine.db.models import ConsensusSnapshot, Paper

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


@respx.mock
def test_detect_contradiction_flags_conflicting_paper():
    respx.post(MESSAGES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "assess_contradiction",
                        "input": {"contradicts": True, "note": "Reports increased risk, contrary to consensus."},
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 50, "output_tokens": 10},
            },
        )
    )

    consensus = ConsensusSnapshot(
        consensus_text="Treatment X reduces risk of outcome Y.",
        is_insufficient_evidence=False,
        model_version="v1",
    )
    paper = Paper(title="A study", abstract="We found treatment X increases risk of outcome Y...")

    result = detect_contradiction(paper, consensus)

    assert result.contradicts is True
    assert "increased risk" in result.note


def test_detect_contradiction_skips_when_consensus_is_insufficient_evidence():
    consensus = ConsensusSnapshot(consensus_text=None, is_insufficient_evidence=True, model_version="v1")
    paper = Paper(title="A study", abstract="Some findings...")

    result = detect_contradiction(paper, consensus)

    assert result.contradicts is False
    assert result.note is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/consensus/test_contradiction.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.consensus.contradiction'`

- [ ] **Step 3: Write `evidence_engine/consensus/contradiction.py`**

```python
from dataclasses import dataclass

from evidence_engine.config import get_settings
from evidence_engine.db.models import ConsensusSnapshot, Paper
from evidence_engine.llm.client import get_anthropic_client

CONTRADICTION_TOOL = {
    "name": "assess_contradiction",
    "description": "Determine whether a paper's claims contradict the current scientific consensus for a topic.",
    "input_schema": {
        "type": "object",
        "properties": {
            "contradicts": {"type": "boolean"},
            "note": {"type": ["string", "null"]},
        },
        "required": ["contradicts", "note"],
    },
}


@dataclass
class ContradictionResult:
    contradicts: bool
    note: str | None


def detect_contradiction(paper: Paper, consensus: ConsensusSnapshot) -> ContradictionResult:
    if consensus.is_insufficient_evidence or not consensus.consensus_text or not paper.abstract:
        return ContradictionResult(contradicts=False, note=None)

    client = get_anthropic_client()
    response = client.messages.create(
        model=get_settings().anthropic_model,
        max_tokens=300,
        tools=[CONTRADICTION_TOOL],
        tool_choice={"type": "tool", "name": "assess_contradiction"},
        messages=[
            {
                "role": "user",
                "content": (
                    f"Current consensus: {consensus.consensus_text}\n\n"
                    f"New paper title: {paper.title}\nNew paper abstract: {paper.abstract}"
                ),
            }
        ],
    )
    for block in response.content:
        if block.type == "tool_use":
            return ContradictionResult(
                contradicts=block.input.get("contradicts", False),
                note=block.input.get("note"),
            )
    return ContradictionResult(contradicts=False, note=None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/consensus/test_contradiction.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evidence_engine/consensus/contradiction.py tests/consensus/test_contradiction.py
git commit -m "feat: add contradiction detection against current consensus"
```

---

## Task 16: Retraction Recheck

**Files:**
- Create: `evidence_engine/adapters/retractions.py`
- Test: `tests/adapters/test_retractions.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.Paper`, `PaperTopic`, `Topic` (Task 2).
- Produces: `evidence_engine.adapters.retractions.recheck_retractions(session: Session, topic: Topic) -> list[Paper]` (returns papers newly marked retracted) — used by Task 18's orchestrator.

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_retractions.py
import httpx
import respx

from evidence_engine.adapters.retractions import recheck_retractions
from evidence_engine.db.models import Paper, PaperTopic, Topic

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


@respx.mock
def test_recheck_retractions_flags_matching_pmid(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    retracted_paper = Paper(pmid="11111111", title="Retracted paper")
    healthy_paper = Paper(pmid="22222222", title="Healthy paper")
    db_session.add_all([retracted_paper, healthy_paper])
    db_session.flush()
    db_session.add_all(
        [
            PaperTopic(paper_id=retracted_paper.id, topic_id=topic.id),
            PaperTopic(paper_id=healthy_paper.id, topic_id=topic.id),
        ]
    )
    db_session.flush()

    respx.get(ESEARCH_URL).mock(
        return_value=httpx.Response(200, json={"esearchresult": {"idlist": ["11111111"]}})
    )

    newly_retracted = recheck_retractions(db_session, topic)

    assert len(newly_retracted) == 1
    assert newly_retracted[0].pmid == "11111111"
    assert retracted_paper.is_retracted is True
    assert healthy_paper.is_retracted is False


def test_recheck_retractions_returns_empty_when_no_papers_have_pmid(db_session):
    topic = Topic(canonical_label="Rare Condition", mesh_id="D000000")
    db_session.add(topic)
    db_session.flush()

    assert recheck_retractions(db_session, topic) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/adapters/test_retractions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.adapters.retractions'`

- [ ] **Step 3: Write `evidence_engine/adapters/retractions.py`**

```python
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential

from evidence_engine.db.models import Paper, PaperTopic, Topic

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
def _search_retracted(pmids: list[str]) -> set[str]:
    pmid_query = " OR ".join(pmids)
    term = f"({pmid_query}) AND retracted publication[Publication Type]"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(ESEARCH_URL, params={"db": "pubmed", "term": term, "retmode": "json", "retmax": "500"})
        resp.raise_for_status()
        return set(resp.json()["esearchresult"]["idlist"])


def recheck_retractions(session: Session, topic: Topic) -> list[Paper]:
    papers = (
        session.execute(
            select(Paper)
            .join(PaperTopic, PaperTopic.paper_id == Paper.id)
            .where(PaperTopic.topic_id == topic.id, Paper.pmid.isnot(None), Paper.is_retracted.is_(False))
        )
        .scalars()
        .all()
    )
    if not papers:
        return []

    pmid_to_paper = {p.pmid: p for p in papers}
    retracted_pmids = _search_retracted(list(pmid_to_paper.keys()))

    newly_retracted = []
    for pmid in retracted_pmids:
        paper = pmid_to_paper.get(pmid)
        if paper:
            paper.is_retracted = True
            newly_retracted.append(paper)
    return newly_retracted
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/adapters/test_retractions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evidence_engine/adapters/retractions.py tests/adapters/test_retractions.py
git commit -m "feat: add retraction recheck against PubMed"
```

---

## Task 17: Change Event Recording

**Files:**
- Create: `evidence_engine/orchestrator/__init__.py`
- Create: `evidence_engine/orchestrator/change_events.py`
- Test: `tests/orchestrator/test_change_events.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.ChangeEvent`, `ChangeEventType`, `Topic`, `Paper` (Task 2).
- Produces: `evidence_engine.orchestrator.change_events.record_change_event(session: Session, topic: Topic, event_type: ChangeEventType, paper: Paper | None = None) -> ChangeEvent` — used by Task 18's orchestrator.

- [ ] **Step 1: Write the failing test**

```python
# tests/orchestrator/test_change_events.py
from evidence_engine.db.models import ChangeEvent, ChangeEventType, Paper, Topic
from evidence_engine.orchestrator.change_events import record_change_event


def test_record_change_event_with_paper(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    paper = Paper(title="A study")
    db_session.add_all([topic, paper])
    db_session.flush()

    event = record_change_event(db_session, topic, ChangeEventType.NEW_PAPER, paper=paper)
    db_session.flush()

    fetched = db_session.query(ChangeEvent).filter_by(id=event.id).one()
    assert fetched.topic_id == topic.id
    assert fetched.paper_id == paper.id
    assert fetched.event_type == ChangeEventType.NEW_PAPER


def test_record_change_event_without_paper(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    event = record_change_event(db_session, topic, ChangeEventType.CONSENSUS_UPDATED)
    db_session.flush()

    assert event.paper_id is None
    assert event.event_type == ChangeEventType.CONSENSUS_UPDATED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestrator/test_change_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.orchestrator.change_events'`

- [ ] **Step 3: Write `evidence_engine/orchestrator/change_events.py`**

```python
from sqlalchemy.orm import Session

from evidence_engine.db.models import ChangeEvent, ChangeEventType, Paper, Topic


def record_change_event(
    session: Session,
    topic: Topic,
    event_type: ChangeEventType,
    paper: Paper | None = None,
) -> ChangeEvent:
    event = ChangeEvent(
        topic_id=topic.id,
        paper_id=paper.id if paper else None,
        event_type=event_type,
    )
    session.add(event)
    session.flush()
    return event
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/orchestrator/test_change_events.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evidence_engine/orchestrator/ tests/orchestrator/test_change_events.py
git commit -m "feat: add change event recording"
```

---

## Task 18: Daily Cycle Orchestrator

**Files:**
- Create: `evidence_engine/orchestrator/cycle.py`
- Test: `tests/orchestrator/test_cycle.py`

**Interfaces:**
- Consumes: `evidence_engine.adapters.base.RawPaper`, `SourceAdapter` (Task 5); `PubMedAdapter` (Task 5), `SemanticScholarAdapter` (Task 6), `ClinicalTrialsAdapter` (Task 7); `merge_raw_papers`, `upsert_paper` (Task 8); `score_paper` (Task 13); `synthesize_consensus` (Task 14); `detect_contradiction` (Task 15); `recheck_retractions` (Task 16); `record_change_event` (Task 17).
- Produces: `evidence_engine.orchestrator.cycle.DEFAULT_ADAPTERS: list[SourceAdapter]` and `evidence_engine.orchestrator.cycle.run_topic_cycle(session: Session, topic: Topic, model_version: str, adapters: list[SourceAdapter] | None = None) -> None` — used by Task 19 and Task 20.

- [ ] **Step 1: Write the failing test**

```python
# tests/orchestrator/test_cycle.py
from unittest.mock import patch

from evidence_engine.adapters.base import RawPaper
from evidence_engine.consensus.contradiction import ContradictionResult
from evidence_engine.db.models import ChangeEvent, ChangeEventType, ConsensusSnapshot, Paper, Score, Topic
from evidence_engine.orchestrator.cycle import run_topic_cycle


class _FailingAdapter:
    def fetch_new(self, topic, since):
        raise RuntimeError("source is down")


class _WorkingAdapter:
    def __init__(self, raw_papers):
        self._raw_papers = raw_papers

    def fetch_new(self, topic, since):
        return self._raw_papers


def test_run_topic_cycle_isolates_adapter_failure_and_scores_new_paper(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    prior_consensus = ConsensusSnapshot(
        topic_id=topic.id,
        consensus_text="Old consensus text",
        is_insufficient_evidence=False,
        model_version="v1",
    )
    db_session.add(prior_consensus)
    db_session.flush()

    raw_paper = RawPaper(source="pubmed", pmid="12345678", doi="10.1/xyz", title="A new trial", abstract="...")
    adapters = [_FailingAdapter(), _WorkingAdapter([raw_paper])]

    fake_consensus = ConsensusSnapshot(
        topic_id=topic.id, consensus_text="Consensus text", is_insufficient_evidence=False, model_version="v1"
    )

    with (
        patch("evidence_engine.orchestrator.cycle.score_paper") as mock_score_paper,
        patch("evidence_engine.orchestrator.cycle.synthesize_consensus", return_value=fake_consensus) as mock_synth,
        patch(
            "evidence_engine.orchestrator.cycle.detect_contradiction",
            return_value=ContradictionResult(True, "Reports opposite direction of effect."),
        ),
        patch("evidence_engine.orchestrator.cycle.recheck_retractions", return_value=[]),
    ):
        run_topic_cycle(db_session, topic, model_version="v1", adapters=adapters)

    mock_score_paper.assert_called_once()
    mock_synth.assert_called_once()

    events = db_session.query(ChangeEvent).filter_by(topic_id=topic.id).all()
    event_types = {e.event_type for e in events}
    assert ChangeEventType.NEW_PAPER in event_types
    assert ChangeEventType.CONSENSUS_UPDATED in event_types
    assert ChangeEventType.CONTRADICTION_FLAGGED in event_types
    assert "opposite direction" in fake_consensus.contradiction_notes
    assert topic.last_checked_at is not None


def test_run_topic_cycle_marks_score_pending_on_scoring_failure(db_session):
    topic = Topic(canonical_label="Myocardial Infarction", mesh_id="68009203")
    db_session.add(topic)
    db_session.flush()

    raw_paper = RawPaper(source="pubmed", pmid="12345678", title="A new trial", abstract="...")

    fake_consensus = ConsensusSnapshot(
        topic_id=topic.id, consensus_text=None, is_insufficient_evidence=True, model_version="v1"
    )

    with (
        patch("evidence_engine.orchestrator.cycle.score_paper", side_effect=RuntimeError("LLM down")),
        patch("evidence_engine.orchestrator.cycle.synthesize_consensus", return_value=fake_consensus),
        patch("evidence_engine.orchestrator.cycle.recheck_retractions", return_value=[]),
    ):
        run_topic_cycle(db_session, topic, model_version="v1", adapters=[_WorkingAdapter([raw_paper])])

    paper = db_session.query(Paper).filter_by(pmid="12345678").one()
    score = db_session.query(Score).filter_by(paper_id=paper.id).one()
    assert score.is_pending is True

    events = db_session.query(ChangeEvent).filter_by(topic_id=topic.id).all()
    assert all(e.event_type != ChangeEventType.NEW_PAPER for e in events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestrator/test_cycle.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.orchestrator.cycle'`

- [ ] **Step 3: Write `evidence_engine/orchestrator/cycle.py`**

```python
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from evidence_engine.adapters.base import RawPaper, SourceAdapter
from evidence_engine.adapters.clinicaltrials import ClinicalTrialsAdapter
from evidence_engine.adapters.merge import merge_raw_papers, upsert_paper
from evidence_engine.adapters.pubmed import PubMedAdapter
from evidence_engine.adapters.retractions import recheck_retractions
from evidence_engine.adapters.semantic_scholar import SemanticScholarAdapter
from evidence_engine.consensus.contradiction import detect_contradiction
from evidence_engine.consensus.synthesizer import synthesize_consensus
from evidence_engine.db.models import ChangeEventType, ConsensusSnapshot, Score, Topic
from evidence_engine.orchestrator.change_events import record_change_event
from evidence_engine.scoring.assemble import score_paper

DEFAULT_ADAPTERS: list[SourceAdapter] = [PubMedAdapter(), SemanticScholarAdapter(), ClinicalTrialsAdapter()]


def _latest_consensus(session: Session, topic: Topic) -> ConsensusSnapshot | None:
    return (
        session.execute(
            select(ConsensusSnapshot)
            .where(ConsensusSnapshot.topic_id == topic.id)
            .order_by(ConsensusSnapshot.generated_at.desc())
        )
        .scalars()
        .first()
    )


def run_topic_cycle(
    session: Session,
    topic: Topic,
    model_version: str,
    adapters: list[SourceAdapter] | None = None,
) -> None:
    adapters = adapters if adapters is not None else DEFAULT_ADAPTERS
    since = topic.last_checked_at
    previous_consensus = _latest_consensus(session, topic)

    raw_papers: list[RawPaper] = []
    for adapter in adapters:
        try:
            raw_papers.extend(adapter.fetch_new(topic, since))
        except Exception:
            continue

    merged = merge_raw_papers(raw_papers)
    contradiction_notes: list[str] = []

    for raw_paper in merged:
        paper = upsert_paper(session, topic, raw_paper)
        session.flush()

        try:
            score_paper(session, paper, citation_count=raw_paper.citation_count or 0, model_version=model_version)
        except Exception:
            existing_score = session.execute(select(Score).where(Score.paper_id == paper.id)).scalar_one_or_none()
            pending = existing_score or Score(paper_id=paper.id, model_version=model_version)
            pending.is_pending = True
            if not existing_score:
                session.add(pending)
            session.flush()
            continue

        record_change_event(session, topic, ChangeEventType.NEW_PAPER, paper=paper)

        if previous_consensus and not previous_consensus.is_insufficient_evidence:
            contradiction = detect_contradiction(paper, previous_consensus)
            if contradiction.contradicts:
                record_change_event(session, topic, ChangeEventType.CONTRADICTION_FLAGGED, paper=paper)
                if contradiction.note:
                    contradiction_notes.append(f"{paper.title}: {contradiction.note}")

    for retracted_paper in recheck_retractions(session, topic):
        record_change_event(session, topic, ChangeEventType.PAPER_RETRACTED, paper=retracted_paper)

    new_consensus = synthesize_consensus(session, topic, model_version=model_version)
    if contradiction_notes:
        new_consensus.contradiction_notes = "\n".join(contradiction_notes)
        session.flush()

    consensus_changed = (
        previous_consensus is None
        or new_consensus.consensus_text != previous_consensus.consensus_text
        or new_consensus.is_insufficient_evidence != previous_consensus.is_insufficient_evidence
    )
    if consensus_changed:
        record_change_event(session, topic, ChangeEventType.CONSENSUS_UPDATED)

    topic.last_checked_at = datetime.utcnow()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/orchestrator/test_cycle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evidence_engine/orchestrator/cycle.py tests/orchestrator/test_cycle.py
git commit -m "feat: add daily cycle orchestrator with adapter-failure isolation"
```

---

## Task 19: Backfill Job for New Topics

**Files:**
- Create: `evidence_engine/orchestrator/backfill.py`
- Test: `tests/orchestrator/test_backfill.py`

**Interfaces:**
- Consumes: `evidence_engine.orchestrator.cycle.run_topic_cycle`, `DEFAULT_ADAPTERS` (Task 18).
- Produces: `evidence_engine.orchestrator.backfill.run_topic_backfill(session: Session, topic: Topic, model_version: str, adapters: list[SourceAdapter] | None = None) -> None` — used by Task 20.

- [ ] **Step 1: Write the failing test**

```python
# tests/orchestrator/test_backfill.py
from datetime import datetime
from unittest.mock import patch

from evidence_engine.db.models import Topic
from evidence_engine.orchestrator.backfill import run_topic_backfill


def test_run_topic_backfill_forces_full_history_fetch(db_session):
    topic = Topic(
        canonical_label="Myocardial Infarction",
        mesh_id="68009203",
        last_checked_at=datetime(2026, 1, 1),
    )
    db_session.add(topic)
    db_session.flush()

    with patch("evidence_engine.orchestrator.backfill.run_topic_cycle") as mock_cycle:
        run_topic_backfill(db_session, topic, model_version="v1")

    assert topic.last_checked_at is None
    mock_cycle.assert_called_once()
    called_topic = mock_cycle.call_args[0][1]
    assert called_topic.last_checked_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestrator/test_backfill.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.orchestrator.backfill'`

- [ ] **Step 3: Write `evidence_engine/orchestrator/backfill.py`**

```python
from sqlalchemy.orm import Session

from evidence_engine.adapters.base import SourceAdapter
from evidence_engine.db.models import Topic
from evidence_engine.orchestrator.cycle import run_topic_cycle


def run_topic_backfill(
    session: Session,
    topic: Topic,
    model_version: str,
    adapters: list[SourceAdapter] | None = None,
) -> None:
    topic.last_checked_at = None
    run_topic_cycle(session, topic, model_version, adapters=adapters)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/orchestrator/test_backfill.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evidence_engine/orchestrator/backfill.py tests/orchestrator/test_backfill.py
git commit -m "feat: add backfill job for newly tracked topics"
```

---

## Task 20: Scheduled Entrypoint Script

**Files:**
- Create: `scripts/__init__.py`
- Create: `scripts/run_daily_cycle.py`
- Create: `README.md` (append run instructions)
- Test: `tests/scripts/test_run_daily_cycle.py`

**Interfaces:**
- Consumes: `evidence_engine.orchestrator.cycle.run_topic_cycle` (Task 18), `evidence_engine.orchestrator.backfill.run_topic_backfill` (Task 19), `evidence_engine.db.session.SessionLocal` (Task 1).
- Produces: `scripts.run_daily_cycle.process_all_topics(session_factory, model_version: str) -> None` and `scripts.run_daily_cycle.main() -> None` — the cron/scheduler entrypoint.

- [ ] **Step 1: Write the failing test**

```python
# tests/scripts/test_run_daily_cycle.py
from datetime import datetime
from unittest.mock import patch

from evidence_engine.db.models import Topic
from scripts.run_daily_cycle import process_all_topics


def test_process_all_topics_dispatches_backfill_for_new_topic_and_isolates_failures(db_session):
    db_session.commit = lambda: None
    db_session.rollback = lambda: None
    db_session.close = lambda: None

    new_topic = Topic(canonical_label="New Topic", mesh_id="D000001", status="active", last_checked_at=None)
    existing_topic = Topic(
        canonical_label="Existing Topic", mesh_id="D000002", status="active", last_checked_at=datetime(2026, 1, 1)
    )
    failing_topic = Topic(
        canonical_label="Failing Topic", mesh_id="D000003", status="active", last_checked_at=datetime(2026, 1, 1)
    )
    db_session.add_all([new_topic, existing_topic, failing_topic])
    db_session.flush()

    def fake_cycle(session, topic, model_version):
        if topic.canonical_label == "Failing Topic":
            raise RuntimeError("boom")

    with (
        patch("scripts.run_daily_cycle.run_topic_backfill") as mock_backfill,
        patch("scripts.run_daily_cycle.run_topic_cycle", side_effect=fake_cycle) as mock_cycle,
    ):
        process_all_topics(lambda: db_session, model_version="v1")

    mock_backfill.assert_called_once()
    assert mock_backfill.call_args[0][1].canonical_label == "New Topic"
    assert mock_cycle.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/scripts/test_run_daily_cycle.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.run_daily_cycle'`

- [ ] **Step 3: Write `scripts/run_daily_cycle.py`**

```python
import logging

from sqlalchemy import select

from evidence_engine.db.models import Topic
from evidence_engine.db.session import SessionLocal
from evidence_engine.orchestrator.backfill import run_topic_backfill
from evidence_engine.orchestrator.cycle import run_topic_cycle

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("daily_cycle")

MODEL_VERSION = "v1"


def process_all_topics(session_factory, model_version: str) -> None:
    session = session_factory()
    try:
        topic_ids = [
            t.id for t in session.execute(select(Topic).where(Topic.status == "active")).scalars().all()
        ]
    finally:
        session.close()

    for topic_id in topic_ids:
        session = session_factory()
        try:
            topic = session.get(Topic, topic_id)
            if topic.last_checked_at is None:
                run_topic_backfill(session, topic, model_version)
            else:
                run_topic_cycle(session, topic, model_version)
            session.commit()
            logger.info("Completed cycle for topic %s", topic.canonical_label)
        except Exception:
            session.rollback()
            logger.exception("Failed cycle for topic %s", topic_id)
        finally:
            session.close()


def main() -> None:
    process_all_topics(SessionLocal, MODEL_VERSION)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/scripts/test_run_daily_cycle.py -v`
Expected: PASS

- [ ] **Step 5: Append run instructions to `README.md`**

```markdown
## Running the daily cycle

Requires `docker compose up -d postgres`, a `.env` file (copy from `.env.example`), and migrations applied via `uv run alembic upgrade head`.

Run once manually:

    uv run python -m scripts.run_daily_cycle

In production, schedule this as a daily cron job / systemd timer / cloud-scheduler-triggered job — no task queue is required for v1 (see spec section 2).
```

- [ ] **Step 6: Commit**

```bash
git add scripts/ tests/scripts/test_run_daily_cycle.py README.md
git commit -m "feat: add scheduled entrypoint script for the daily cycle"
```

---

## Task 21: Golden-Set Evaluation Harness

**Files:**
- Create: `tests/fixtures/golden_set/classification_golden_set.json`
- Create: `evidence_engine/eval/__init__.py`
- Create: `evidence_engine/eval/classification_eval.py`
- Test: `tests/eval/test_classification_eval.py`

**Interfaces:**
- Consumes: `evidence_engine.db.models.Paper`, `StudyType` (Task 2), `evidence_engine.scoring.classifier.classify_study_type` (Task 9).
- Produces: `evidence_engine.eval.classification_eval.EvalResult` (dataclass: `accuracy: float`, `mismatches: list[dict]`) and `evidence_engine.eval.classification_eval.run_classification_eval(golden_set_path: str) -> EvalResult`. This is the harness the spec (section 7) requires to run whenever the classification prompt/model changes, gating deploys on non-regression.

- [ ] **Step 1: Create the golden-set fixture**

Note: this fixture starts with 6 entries to exercise the harness end-to-end. Per spec section 7, grow this to 50-100 expert-labeled papers before relying on it as a deploy gate.

```json
[
  {
    "title": "A large multicenter randomized trial of Drug X",
    "abstract": "Patients were randomly assigned to receive Drug X or placebo...",
    "publication_types": ["Randomized Controlled Trial"],
    "expected_study_type": "rct"
  },
  {
    "title": "Pooled analysis of 12 trials of Drug X",
    "abstract": "We performed a meta-analysis pooling data from 12 randomized trials...",
    "publication_types": ["Meta-Analysis"],
    "expected_study_type": "meta_analysis"
  },
  {
    "title": "A single patient case of rare reaction to Drug X",
    "abstract": "We report a 45-year-old patient who developed...",
    "publication_types": ["Case Reports"],
    "expected_study_type": "case_series"
  },
  {
    "title": "Perspectives on the future of Drug X research",
    "abstract": "In this editorial, we discuss emerging directions...",
    "publication_types": ["Editorial"],
    "expected_study_type": "opinion_editorial"
  },
  {
    "title": "Long-term outcomes in patients prescribed Drug X",
    "abstract": "We followed a cohort of 1,200 patients prescribed Drug X for five years, comparing outcomes to a matched untreated cohort...",
    "publication_types": [],
    "expected_study_type": "cohort"
  },
  {
    "title": "A systematic review of Drug X safety literature",
    "abstract": "We systematically searched three databases and reviewed 40 studies on the safety of Drug X...",
    "publication_types": [],
    "expected_study_type": "systematic_review"
  }
]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/eval/test_classification_eval.py
import pytest

from evidence_engine.eval.classification_eval import run_classification_eval


@pytest.mark.eval
def test_classification_golden_set_accuracy_meets_bar():
    result = run_classification_eval("tests/fixtures/golden_set/classification_golden_set.json")
    assert result.accuracy >= 0.8, f"Mismatches: {result.mismatches}"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/eval/test_classification_eval.py -v -m eval`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.eval.classification_eval'`

- [ ] **Step 4: Write `evidence_engine/eval/classification_eval.py`**

```python
import json
from dataclasses import dataclass

from evidence_engine.db.models import Paper, StudyType
from evidence_engine.scoring.classifier import classify_study_type


@dataclass
class EvalResult:
    accuracy: float
    mismatches: list[dict]


def run_classification_eval(golden_set_path: str) -> EvalResult:
    with open(golden_set_path, encoding="utf-8") as f:
        cases = json.load(f)

    mismatches = []
    correct = 0
    for case in cases:
        paper = Paper(
            title=case["title"],
            abstract=case["abstract"],
            publication_types=case["publication_types"],
        )
        predicted = classify_study_type(paper)
        expected = StudyType(case["expected_study_type"])
        if predicted == expected:
            correct += 1
        else:
            mismatches.append({"title": case["title"], "expected": expected.value, "predicted": predicted.value})

    accuracy = correct / len(cases) if cases else 0.0
    return EvalResult(accuracy=accuracy, mismatches=mismatches)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/eval/test_classification_eval.py -v -m eval`
Expected: PASS (requires a real `ANTHROPIC_API_KEY` in `.env`, since the three cases without a matching `publication_types` tag fall through to a live LLM call — this test is excluded from the default `pytest` run via the `-m "not eval"` addopts set in Task 1, and should be run explicitly, e.g. in a separate CI job, whenever the classification prompt or model changes)

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/golden_set/ evidence_engine/eval/ tests/eval/test_classification_eval.py
git commit -m "feat: add golden-set evaluation harness for study-type classification"
```

---

## Task 22: Consensus LLM-as-Judge Evaluation Harness

**Note on scope:** per spec section 7, consensus quality is judged against expert-reviewed expected themes via an LLM-as-judge check. This task implements the judge as a standalone function operating on `(consensus_text, expected_themes, forbidden_claims)`, with a golden-set fixture of pre-recorded consensus text. This decouples the judge from needing to re-run `synthesize_consensus` against seeded database fixtures each time — the golden-set fixture's `consensus_text` entries should be periodically refreshed by actually running `synthesize_consensus` against real topics and having a domain expert review the output before locking it into the fixture.

**Files:**
- Create: `tests/fixtures/golden_set/consensus_golden_set.json`
- Create: `evidence_engine/eval/consensus_eval.py`
- Test: `tests/eval/test_consensus_eval.py`

**Interfaces:**
- Consumes: `evidence_engine.llm.client.get_anthropic_client` (Task 9).
- Produces: `evidence_engine.eval.consensus_eval.JudgeResult` (dataclass: `passed: bool`, `reasoning: str`), `judge_consensus_text(consensus_text: str, expected_themes: list[str], forbidden_claims: list[str]) -> JudgeResult`, `ConsensusEvalResult` (dataclass: `pass_rate: float`, `failures: list[dict]`), and `run_consensus_eval(golden_set_path: str) -> ConsensusEvalResult`.

- [ ] **Step 1: Create the golden-set fixture**

```json
[
  {
    "topic_label": "Myocardial Infarction",
    "consensus_text": "Meta-analyses and systematic reviews of aspirin therapy following myocardial infarction consistently show a reduction in recurrent cardiovascular events and mortality, with benefit most pronounced when started early post-event.",
    "expected_themes": ["aspirin reduces recurrent cardiovascular events", "benefit is well established in high-quality evidence"],
    "forbidden_claims": ["aspirin has no effect", "aspirin is harmful in all patients"]
  },
  {
    "topic_label": "Long COVID",
    "consensus_text": "Evidence on effective treatments for long COVID remains limited, with most available studies being small observational cohorts rather than randomized trials; no single intervention has yet been established as consistently effective.",
    "expected_themes": ["evidence base is still limited", "no single treatment is firmly established"],
    "forbidden_claims": ["a specific drug has been proven to cure long COVID"]
  }
]
```

- [ ] **Step 2: Write the failing test**

```python
# tests/eval/test_consensus_eval.py
import httpx
import respx

from evidence_engine.eval.consensus_eval import judge_consensus_text, run_consensus_eval

MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def _mock_judge_response(passed: bool, reasoning: str):
    return httpx.Response(
        200,
        json={
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4-6",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "judge_consensus",
                    "input": {"passed": passed, "reasoning": reasoning},
                }
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 50, "output_tokens": 10},
        },
    )


@respx.mock
def test_judge_consensus_text_returns_structured_result():
    respx.post(MESSAGES_URL).mock(return_value=_mock_judge_response(True, "Covers both expected themes."))

    result = judge_consensus_text(
        consensus_text="Aspirin reduces recurrent events after MI, per multiple meta-analyses.",
        expected_themes=["aspirin reduces recurrent events"],
        forbidden_claims=["aspirin is harmful in all patients"],
    )

    assert result.passed is True
    assert "expected themes" in result.reasoning


@respx.mock
def test_run_consensus_eval_aggregates_pass_rate():
    respx.post(MESSAGES_URL).mock(
        side_effect=[
            _mock_judge_response(True, "Matches expectations."),
            _mock_judge_response(False, "Missing the 'limited evidence' theme."),
        ]
    )

    result = run_consensus_eval("tests/fixtures/golden_set/consensus_golden_set.json")

    assert result.pass_rate == 0.5
    assert len(result.failures) == 1
    assert result.failures[0]["topic_label"] == "Long COVID"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/eval/test_consensus_eval.py -v -m eval`
Expected: FAIL with `ModuleNotFoundError: No module named 'evidence_engine.eval.consensus_eval'`

- [ ] **Step 4: Write `evidence_engine/eval/consensus_eval.py`**

```python
import json
from dataclasses import dataclass

from evidence_engine.config import get_settings
from evidence_engine.llm.client import get_anthropic_client

JUDGE_TOOL = {
    "name": "judge_consensus",
    "description": "Judge whether a consensus paragraph reflects the expected themes and avoids forbidden claims.",
    "input_schema": {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": ["passed", "reasoning"],
    },
}


@dataclass
class JudgeResult:
    passed: bool
    reasoning: str


@dataclass
class ConsensusEvalResult:
    pass_rate: float
    failures: list[dict]


def judge_consensus_text(consensus_text: str, expected_themes: list[str], forbidden_claims: list[str]) -> JudgeResult:
    themes_block = "\n".join(f"- {t}" for t in expected_themes)
    forbidden_block = "\n".join(f"- {c}" for c in forbidden_claims)
    prompt = (
        f"Consensus paragraph:\n{consensus_text}\n\n"
        f"Expected themes it should include:\n{themes_block}\n\n"
        f"Claims it must NOT make:\n{forbidden_block}\n\n"
        "Judge whether the paragraph includes all expected themes and none of the forbidden claims."
    )

    client = get_anthropic_client()
    response = client.messages.create(
        model=get_settings().anthropic_model,
        max_tokens=300,
        tools=[JUDGE_TOOL],
        tool_choice={"type": "tool", "name": "judge_consensus"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return JudgeResult(passed=block.input.get("passed", False), reasoning=block.input.get("reasoning", ""))
    return JudgeResult(passed=False, reasoning="No judgment returned")


def run_consensus_eval(golden_set_path: str) -> ConsensusEvalResult:
    with open(golden_set_path, encoding="utf-8") as f:
        cases = json.load(f)

    failures = []
    passed_count = 0
    for case in cases:
        result = judge_consensus_text(case["consensus_text"], case["expected_themes"], case["forbidden_claims"])
        if result.passed:
            passed_count += 1
        else:
            failures.append({"topic_label": case["topic_label"], "reasoning": result.reasoning})

    pass_rate = passed_count / len(cases) if cases else 0.0
    return ConsensusEvalResult(pass_rate=pass_rate, failures=failures)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/eval/test_consensus_eval.py -v -m eval`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/golden_set/consensus_golden_set.json evidence_engine/eval/consensus_eval.py tests/eval/test_consensus_eval.py
git commit -m "feat: add LLM-as-judge evaluation harness for consensus synthesis"
```
