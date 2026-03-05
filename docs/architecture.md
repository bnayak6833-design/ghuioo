# OpenTrain Architecture

## Overview

OpenTrain is a three-component distributed system: a **coordinator server**, one or more **worker nodes**, and a **web dashboard**. Workers use a pull model — they poll the coordinator for tasks rather than having tasks pushed to them. This simplifies NAT traversal, makes worker churn safe, and keeps the coordinator stateless with respect to worker connectivity.

---

## Component Interaction

```
┌─────────────────────────────────────────────────────────────┐
│                      Web Dashboard                          │
│   (Next.js — job submission, live monitoring, download)     │
└───────────────────────┬─────────────────────────────────────┘
                        │ REST (HTTP)
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                   Coordinator Server                        │
│   (FastAPI — schedules tasks, tracks workers, aggregates)   │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐ │
│  │  Job Store   │  │  Task Queue  │  │  Worker Registry  │ │
│  │  (SQLite)    │  │  (SQLite)    │  │  (SQLite)         │ │
│  └──────────────┘  └──────────────┘  └───────────────────┘ │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Background Scheduler (APScheduler)                  │   │
│  │  · check_heartbeats   (every 30s)                    │   │
│  │  · check_task_timeouts (every 30s)                   │   │
│  │  · check_stalled_jobs  (every 60s)                   │   │
│  └──────────────────────────────────────────────────────┘   │
└───────────────────────┬─────────────────────────────────────┘
                        │ REST (HTTP, pull model)
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
      Worker A      Worker B      Worker C
  (sentence-     (sentence-    (sentence-
   transformers)  transformers)  transformers)
```

---

## Data Model

### Job

Represents a user-submitted ML workload.

| Field         | Type     | Description                                      |
|---------------|----------|--------------------------------------------------|
| id            | UUID     | Primary key                                      |
| status        | string   | `pending` → `in_progress` → `completed`/`failed` |
| job_type      | string   | `embedding`, `tokenize`, `preprocess`            |
| dataset_text  | text     | Raw input dataset (one item per line)            |
| chunk_size    | integer  | Lines per task shard                             |
| total_tasks   | integer  | Number of shards created                         |
| done_tasks    | integer  | Completed task count (updated per result)        |
| created_at    | datetime |                                                  |
| completed_at  | datetime | Set when aggregation finishes                    |

### Task

One unit of work — a single dataset shard.

| Field        | Type     | Description                                            |
|--------------|----------|--------------------------------------------------------|
| id           | UUID     | Primary key                                            |
| job_id       | UUID     | Foreign key → Job                                      |
| task_index   | integer  | Position in job (used for ordered aggregation)         |
| status       | string   | `pending` → `assigned` → `completed`/`failed`          |
| worker_id    | UUID     | Foreign key → Worker (null if unassigned)              |
| payload      | JSON     | `{"data": [...], "config": {"job_type": "..."}}`       |
| result       | JSON     | Worker output (null until completed)                   |
| checksum     | string   | SHA-256 of payload data for integrity verification     |
| assigned_at  | datetime | When task was claimed by a worker                      |
| completed_at | datetime | When result was accepted                               |
| attempts     | integer  | Incremented on each assignment                         |

### Worker

A registered volunteer node.

| Field          | Type     | Description                              |
|----------------|----------|------------------------------------------|
| id             | UUID     | Primary key, issued at registration      |
| status         | string   | `idle`, `busy`, `offline`                |
| last_heartbeat | datetime | Updated by `POST /workers/heartbeat`     |
| tasks_done     | integer  | Lifetime completed task count            |
| registered_at  | datetime |                                          |
| hostname       | string   | Optional, reported by worker at startup  |

---

## Task Lifecycle

```
          submit job
               │
               ▼
         [sharding]
               │
        ┌──────┴──────────────────────────────┐
        ▼             ▼                        ▼
    Task 0         Task 1        ...        Task N
   (pending)      (pending)               (pending)
        │
        │  GET /tasks/next
        ▼
   (assigned) ──── worker processes ────▶ (completed)
        │                                      │
        │  timeout / worker dropout            │
        ▼                                      │
   (pending) ◀── requeue (attempts < 3)        │
        │                                      │
        │  attempts >= 3                       │
        ▼                                      │
    (failed)                                   │
                                               │
                          all tasks completed  │
                                               ▼
                                        [aggregation]
                                               │
                                               ▼
                                        job → completed
                                        artifact written
```

---

## Reliability Design

### Heartbeat monitor

Workers POST `/workers/heartbeat` every 30 seconds. The background scheduler checks every 30 seconds for workers whose `last_heartbeat` is older than 60 seconds. Stale workers are marked `offline` and their assigned tasks are returned to `pending` (or marked `failed` if `attempts >= MAX_TASK_ATTEMPTS`).

### Task timeout

Tasks assigned but not completed within 5 minutes are independently timed out by the scheduler — even if the worker is still sending heartbeats. This catches workers that are alive but hung on a single task.

### Stalled job recovery

A lower-frequency pass (every 60s) scans jobs in `in_progress` status and re-derives their true completion state from the database. Catches edge cases where `done_tasks` drifted out of sync due to concurrent result submissions.

### Concurrency during aggregation

The aggregator uses a per-job `threading.Lock` to prevent two threads from aggregating the same job simultaneously. The lock is non-blocking — a second concurrent call immediately backs off. Artifacts are written atomically via `tempfile` + `os.replace`.

### Checksum verification

Workers compute a SHA-256 of their result payload before sending. The coordinator independently recomputes the checksum and rejects submissions that don't match.

---

## Pull Model vs Push Model

OpenTrain uses pull (workers request tasks) rather than push (coordinator sends tasks to workers).

**Advantages of pull:**
- Works across NAT — workers only need outbound HTTP
- Handles worker churn naturally — disappeared workers just stop pulling
- No connection state to maintain on the coordinator
- Workers can self-throttle by adjusting poll interval

**Trade-offs:**
- Slightly higher latency between task completion and next assignment (~poll interval)
- More HTTP requests at idle (workers polling when queue is empty)

For ML workloads where each task takes seconds to minutes, the polling overhead is negligible.

---

## Scaling Considerations

The MVP uses SQLite which is single-writer. For higher concurrency:

- Replace SQLite with **PostgreSQL** — drop-in via SQLAlchemy connection string change
- The coordinator itself is stateless (no in-memory task state) so it can be horizontally scaled behind a load balancer once on Postgres
- Workers scale linearly — each additional worker increases throughput proportionally up to the coordinator's API capacity