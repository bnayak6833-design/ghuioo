# API Reference

Base URL: `http://localhost:8000` (development)

Interactive docs (Swagger UI): `http://localhost:8000/docs`

---

## Jobs

### POST /jobs

Submit a new ML job. The dataset is immediately sharded into tasks.

**Request body:**
```json
{
  "job_type": "embedding",
  "dataset_text": "line one\nline two\nline three",
  "chunk_size": 100
}
```

| Field         | Type    | Required | Description                                   |
|---------------|---------|----------|-----------------------------------------------|
| job_type      | string  | yes      | `embedding`, `tokenize`, or `preprocess`      |
| dataset_text  | string  | yes      | Raw text, one item per line (max 50,000 lines)|
| chunk_size    | integer | no       | Lines per shard, default 100 (range 1–5000)   |

**Response `201`:**
```json
{
  "id": "3f2a1b4c-...",
  "status": "in_progress",
  "job_type": "embedding",
  "chunk_size": 100,
  "total_tasks": 10,
  "done_tasks": 0,
  "created_at": "2024-01-15T10:30:00",
  "completed_at": null,
  "progress_pct": 0.0
}
```

---

### GET /jobs

List all jobs, most recent first.

**Response `200`:** Array of job objects (same schema as above).

---

### GET /jobs/{job_id}

Get full job detail including per-task status breakdown.

**Response `200`:**
```json
{
  "id": "3f2a1b4c-...",
  "status": "in_progress",
  "progress_pct": 42.0,
  "total_tasks": 10,
  "done_tasks": 4,
  "tasks": [
    {
      "id": "a1b2c3d4-...",
      "task_index": 0,
      "status": "completed",
      "worker_id": "w1x2y3z4-...",
      "assigned_at": "2024-01-15T10:30:05",
      "completed_at": "2024-01-15T10:30:12",
      "attempts": 1
    }
  ]
}
```

**Errors:** `404` if job not found.

---

### GET /jobs/{job_id}/result

Download the merged result artifact as a JSON file.

**Response `200`:** JSON file download (`Content-Disposition: attachment`).

```json
{
  "job_id": "3f2a1b4c-...",
  "job_type": "embedding",
  "total_tasks": 10,
  "total_items": 1000,
  "completed_at": "2024-01-15T10:35:00Z",
  "wall_seconds": 300.4,
  "result": [[0.12, -0.34, ...], ...]
}
```

**Errors:** `404` if job not found or artifact missing. `409` if job not yet completed.

---

### GET /jobs/{job_id}/result/summary

Lightweight metadata about a completed job's result — no payload.

**Response `200`:**
```json
{
  "job_id": "3f2a1b4c-...",
  "job_type": "embedding",
  "total_tasks": 10,
  "total_items": 1000,
  "wall_seconds": 300.4,
  "completed_at": "2024-01-15T10:35:00Z",
  "artifact_size_bytes": 204800
}
```

---

## Tasks

### GET /tasks/next

Worker polls for the next available task. Returns `null` (200 with empty body) if no tasks are available.

**Query params:**

| Param     | Required | Description            |
|-----------|----------|------------------------|
| worker_id | yes      | UUID from registration |

**Response `200`:**
```json
{
  "task_id": "a1b2c3d4-...",
  "job_id": "3f2a1b4c-...",
  "task_index": 5,
  "job_type": "embedding",
  "payload": "{\"data\": [\"text 1\", \"text 2\"], \"config\": {\"job_type\": \"embedding\"}}"
}
```

Returns `null` if queue is empty.

**Errors:** `404` if worker not registered. `403` if worker is offline.

---

### POST /tasks/{task_id}/result

Worker submits completed result.

**Request body:**
```json
{
  "worker_id": "w1x2y3z4-...",
  "result": "{\"embeddings\": [[0.1, 0.2, ...]]}",
  "checksum": "sha256-hex-string"
}
```

The `checksum` is the SHA-256 of `json.dumps(result_dict, sort_keys=True)`.

**Response `200`:**
```json
{
  "status": "ok",
  "task_id": "a1b2c3d4-...",
  "job_progress": "5/10"
}
```

**Errors:** `400` checksum mismatch. `403` worker ID mismatch. `404` task not found.

---

### POST /tasks/{task_id}/fail

Worker reports that it could not complete a task.

**Request body:**
```json
{
  "worker_id": "w1x2y3z4-...",
  "error": "OOM: model.encode failed on shard"
}
```

**Response `200`:**
```json
{
  "status": "requeued",
  "message": "Task returned to queue (attempt 2/3).",
  "error": "OOM: model.encode failed on shard"
}
```

Or if max attempts reached:
```json
{
  "status": "failed",
  "message": "Task exceeded max attempts (3). Job marked failed."
}
```

---

## Workers

### POST /workers/register

Register a new volunteer worker. Returns a `worker_id` the client must use in all subsequent calls.

**Request body:**
```json
{
  "hostname": "my-laptop"
}
```

`hostname` is optional.

**Response `201`:**
```json
{
  "worker_id": "w1x2y3z4-...",
  "message": "Registered successfully. Poll GET /tasks/next?worker_id=w1x2y3z4-... to begin."
}
```

---

### POST /workers/heartbeat

Worker signals it is alive. Should be called every ~30 seconds.

**Request body:**
```json
{
  "worker_id": "w1x2y3z4-..."
}
```

**Response `200`:**
```json
{
  "status": "ok",
  "worker_id": "w1x2y3z4-..."
}
```

**Errors:** `404` if worker not found (worker should re-register).

---

### GET /workers

List all registered workers.

**Response `200`:**
```json
[
  {
    "id": "w1x2y3z4-...",
    "status": "busy",
    "last_heartbeat": "2024-01-15T10:34:55",
    "tasks_done": 42,
    "registered_at": "2024-01-15T09:00:00",
    "hostname": "my-laptop"
  }
]
```

---

## Health

### GET /health

Simple liveness check.

**Response `200`:**
```json
{ "status": "ok" }
```