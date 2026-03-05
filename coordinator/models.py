"""
Database models and session management for OpenTrain coordinator.
Uses SQLite via SQLAlchemy for MVP simplicity.
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Integer, DateTime,
    ForeignKey, Text, Float
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

import os

# Allow overriding the database via an environment variable. Render
# environments can supply a managed Postgres or other SQL URL using
# DATABASE_URL. In the absence of one we default to a SQLite file located
# inside the coordinator package so that the location is deterministic
# regardless of the current working directory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(BASE_DIR, 'opentrain.db')}"
)

# SQLAlchemy engine setup needs a special flag when using SQLite in
# conjunction with FastAPI's threaded server; other databases don't.
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},  # needed for SQLite + FastAPI
    )
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def new_uuid() -> str:
    return str(uuid.uuid4())


# ─── Job ──────────────────────────────────────────────────────────────────────

class Job(Base):
    __tablename__ = "jobs"

    id           = Column(String, primary_key=True, default=new_uuid)
    status       = Column(String, default="pending")      # pending | in_progress | completed | failed
    job_type     = Column(String, nullable=False)          # embedding | tokenize | preprocess
    dataset_text = Column(Text, nullable=True)             # raw text uploaded by user
    chunk_size   = Column(Integer, default=100)
    total_tasks  = Column(Integer, default=0)
    done_tasks   = Column(Integer, default=0)
    created_at   = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    tasks = relationship("Task", back_populates="job", cascade="all, delete-orphan")


# ─── Task ─────────────────────────────────────────────────────────────────────

class Task(Base):
    __tablename__ = "tasks"

    id           = Column(String, primary_key=True, default=new_uuid)
    job_id       = Column(String, ForeignKey("jobs.id"), nullable=False)
    task_index   = Column(Integer, nullable=False)         # position in job for ordered aggregation
    status       = Column(String, default="pending")       # pending | assigned | completed | failed
    worker_id    = Column(String, ForeignKey("workers.id"), nullable=True)
    payload      = Column(Text, nullable=False)            # JSON: {data: [...], config: {...}}
    result       = Column(Text, nullable=True)             # JSON result from worker
    checksum     = Column(String, nullable=True)           # SHA-256 of payload data for integrity
    assigned_at  = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    attempts     = Column(Integer, default=0)

    job    = relationship("Job", back_populates="tasks")
    worker = relationship("Worker", back_populates="tasks")


# ─── Worker ───────────────────────────────────────────────────────────────────

class Worker(Base):
    __tablename__ = "workers"

    id             = Column(String, primary_key=True, default=new_uuid)
    status         = Column(String, default="idle")        # idle | busy | offline
    last_heartbeat = Column(DateTime, default=datetime.utcnow)
    tasks_done     = Column(Integer, default=0)
    registered_at  = Column(DateTime, default=datetime.utcnow)
    hostname       = Column(String, nullable=True)         # optional: volunteer's machine name

    tasks = relationship("Task", back_populates="worker")


def create_tables():
    Base.metadata.create_all(bind=engine)