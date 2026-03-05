"""
aggregator.py — Merges completed task results into a final job artifact.

Called by:
  - routes/tasks.py  when the last result comes in (hot path)
  - scheduler.py     when check_stalled_jobs detects a stuck job (recovery path)

Guarantees:
  - Concurrency-safe: a threading lock prevents two callers from aggregating
    the same job simultaneously (e.g. last two results arriving at the same
    time from different workers).
  - Atomic write: artifact is written to a temp file then renamed, so the
    download endpoint never sees a partial file.
  - Idempotent: if the artifact already exists and the job is already marked
    completed, returns True immediately without re-processing.
"""

import json
import os
import tempfile
import threading
from datetime import datetime

from sqlalchemy.orm import Session

from .models import Job, Task

# Place artifacts in a folder adjacent to this module so that it's
# deterministic regardless of the current working directory. This makes
# deploys (e.g. on Render) behave the same as local `cd coordinator` runs.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_DIR = os.path.join(BASE_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# Per-job locks: prevents two concurrent requests from both triggering
# aggregation for the same job at the same time.
_job_locks: dict[str, threading.Lock] = {}
_locks_mutex = threading.Lock()


def _get_job_lock(job_id: str) -> threading.Lock:
    with _locks_mutex:
        if job_id not in _job_locks:
            _job_locks[job_id] = threading.Lock()
        return _job_locks[job_id]


def _release_job_lock(job_id: str):
    """Clean up lock entry after job completes to avoid unbounded dict growth."""
    with _locks_mutex:
        _job_locks.pop(job_id, None)


# ─── Public entry point ───────────────────────────────────────────────────────

def try_aggregate_job(job_id: str, db: Session) -> bool:
    """
    Attempt to aggregate results for a completed job.

    Thread-safe: uses a per-job lock so only one thread aggregates at a time.
    Idempotent: safe to call multiple times; will no-op if already completed.

    Returns True if aggregation succeeded (or was already done), False otherwise.
    """
    lock = _get_job_lock(job_id)

    if not lock.acquire(blocking=False):
        # Another thread is already aggregating this job
        print(f"[aggregator] Job {job_id[:8]}… aggregation already in progress, skipping.")
        return False

    try:
        return _aggregate(job_id, db)
    finally:
        lock.release()


# ─── Core aggregation ─────────────────────────────────────────────────────────

def _aggregate(job_id: str, db: Session) -> bool:
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        print(f"[aggregator] Job {job_id[:8]}… not found.")
        return False

    # Idempotency check — already done
    out_path = artifact_path(job_id)
    if job.status == "completed" and os.path.exists(out_path):
        print(f"[aggregator] Job {job_id[:8]}… already completed, skipping.")
        return True

    # Load and validate all tasks
    tasks = (
        db.query(Task)
        .filter(Task.job_id == job_id)
        .order_by(Task.task_index)
        .all()
    )

    incomplete = [t for t in tasks if t.status != "completed"]
    if incomplete:
        statuses = {t.status for t in incomplete}
        print(
            f"[aggregator] Job {job_id[:8]}… has {len(incomplete)} incomplete tasks "
            f"(statuses: {statuses}). Skipping aggregation."
        )
        return False

    # Merge results
    print(f"[aggregator] Merging {len(tasks)} tasks for job {job_id[:8]}… (type={job.job_type})")
    merged, stats = _merge_results(job.job_type, tasks)

    # Build artifact with metadata
    completed_at = datetime.utcnow()
    artifact = {
        "job_id":       job_id,
        "job_type":     job.job_type,
        "total_tasks":  len(tasks),
        "total_items":  stats["total_items"],
        "completed_at": completed_at.isoformat() + "Z",
        "wall_seconds": (completed_at - job.created_at).total_seconds(),
        "result":       merged,
    }

    # Atomic write: write to temp file, then rename into place
    tmp_fd, tmp_path = tempfile.mkstemp(dir=RESULTS_DIR, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as f:
            json.dump(artifact, f)
        os.replace(tmp_path, out_path)   # atomic on POSIX
    except Exception as e:
        os.unlink(tmp_path)
        print(f"[aggregator] Failed to write artifact for job {job_id[:8]}…: {e}")
        return False

    # Mark job complete in DB
    job.status       = "completed"
    job.completed_at = completed_at
    db.commit()

    print(
        f"[aggregator] ✓ Job {job_id[:8]}… complete — "
        f"{stats['total_items']} items, {artifact['wall_seconds']:.1f}s wall time. "
        f"Artifact: {out_path}"
    )
    return True


# ─── Merge strategies ─────────────────────────────────────────────────────────

def _merge_results(job_type: str, tasks: list) -> tuple[list, dict]:
    """
    Merge task results in task_index order according to job type.

    Returns:
        merged: the combined result list
        stats:  metadata dict (currently just total_items)
    """
    merged = []

    for task in tasks:
        if not task.result:
            # Shouldn't happen at this point, but be defensive
            print(f"[aggregator] Warning: task {task.id[:8]}… has no result, skipping.")
            continue

        data = json.loads(task.result)

        if job_type == "embedding":
            # Worker returns: {"embeddings": [[float, ...], ...]}
            items = data.get("embeddings", [])

        elif job_type in ("tokenize", "preprocess"):
            # Worker returns: {"output": [...]}
            items = data.get("output", [])

        else:
            # Unknown type: wrap raw result so it's still addressable by index
            items = [{"task_index": task.task_index, "data": data}]

        merged.extend(items)

    return merged, {"total_items": len(merged)}


# ─── Artifact helpers (used by download endpoint) ────────────────────────────

def artifact_path(job_id: str) -> str:
    return os.path.join(RESULTS_DIR, f"{job_id}.json")


def artifact_exists(job_id: str) -> bool:
    return os.path.exists(artifact_path(job_id))