"""
Database layer for the mock pipeline service.

Schema design notes (see README for full rationale):
- `jobs` table is the single source of truth for job lifecycle + result.
- `output` is stored as JSONB so we don't need to pre-define every possible
  measurement field the "pipeline" might produce.
- `status` is a plain string column with an application-level enum/check
  rather than a Postgres ENUM type, to keep migrations simple (adding a new
  status later is a one-line change, not a type migration).
- Timestamps (`created_at`, `updated_at`, `completed_at`) let the harness
  compute latency / reliability metrics without re-deriving them.
"""

import os
import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    create_engine,
    Column,
    String,
    DateTime,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/pipeline_test",
)

# pool_pre_ping avoids "stale connection" errors when the harness/tests hold
# the process open for a while between DB hits.
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Base):
    __tablename__ = "jobs"

    job_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    input_type = Column(String, nullable=False, index=True)
    input_ref = Column(String, nullable=True)  # filename / identifier of the input
    status = Column(SAEnum(JobStatus, name="job_status"), nullable=False, default=JobStatus.QUEUED, index=True)
    output = Column(JSONB, nullable=True)
    error = Column(String, nullable=True)
    # Test-only hook: lets callers (e.g. the test suite) override the mock's
    # fault-injection rates per job, so tests don't have to be flaky against
    # the default random fail/wrong/late rates. Never used by the harness
    # against a "real" pipeline - this is purely a mock-service affordance.
    fault_overrides = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "status": self.status.value if isinstance(self.status, JobStatus) else self.status,
            "input_type": self.input_type,
            "output": self.output,
        }


def init_db():
    Base.metadata.create_all(bind=engine)


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
