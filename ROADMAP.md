# OpenTrain Roadmap

This document tracks planned improvements beyond the MVP. Items are roughly ordered by impact and implementation complexity.

---

## Near-Term

**GPU scheduling**
Detect CUDA-capable worker devices at registration time and assign embedding/inference tasks preferentially to GPU workers. Workers report `{"has_gpu": true, "vram_gb": 8}` at registration; coordinator stores this and uses it during task assignment.

**Additional workload types**
- `batch_inference` — run any HuggingFace model on a text shard
- `dataset_filter` — filter rows matching a condition
- `chunk_embed` — embed with configurable model name per job

**Worker reputation system**
Track task completion rate, average processing time, and failure rate per worker. Deprioritize workers with high failure rates. Surface stats in the dashboard.

**Token-based authentication**
Generate join tokens from the dashboard. Workers must present a valid token at registration. Prevents unauthorized use of a public coordinator.

---

## Medium-Term

**Dataset connectors**
Pull datasets directly from:
- HuggingFace Hub (`datasets.load_dataset`)
- S3 / GCS bucket paths
- Public URLs

Users would supply a dataset reference string instead of pasting raw text.

**WebSocket streaming**
Replace the dashboard's polling loop with a WebSocket connection to the coordinator. Push task completion events in real time — lower latency and less coordinator load at scale.

**Worker resource reporting**
Workers periodically report CPU %, RAM usage, and available VRAM. Coordinator uses this for smarter scheduling — avoid assigning large tasks to memory-constrained workers.

**Multi-coordinator federation**
Run multiple coordinator instances sharing state via a Redis backend. Enables horizontal scaling of the coordinator itself and geographic distribution.

---

## Long-Term

**Distributed model training**
Gradient aggregation across workers (data-parallel training). Each worker computes gradients on its shard; the coordinator aggregates and broadcasts updated weights. This is the "full OpenTrain vision" but requires significantly more engineering.

**Decentralized coordination**
Replace the central coordinator with a peer-to-peer coordination protocol. Workers discover each other and elect a temporary coordinator. Removes the single point of failure.

**Incentive layer**
A credit system that rewards volunteers for contributed compute and charges job submitters. Credits could be earned by running a worker and spent by submitting jobs.

**Hosted public network**
A publicly accessible OpenTrain coordinator that anyone can submit jobs to and anyone can contribute workers to — a shared volunteer ML compute commons.

---

## Known Limitations (MVP)

- SQLite is single-writer; at high concurrency (many workers submitting results simultaneously), use Postgres instead
- No authentication on job submission — anyone who can reach the coordinator can submit jobs
- Worker model is loaded fresh per process; no shared memory between workers on the same machine
- Result artifacts are stored on local disk; coordinator restarts lose the path if the volume isn't mounted

---

Contributions toward any roadmap item are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).