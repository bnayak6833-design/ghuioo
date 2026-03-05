"""
OpenTrain Coordinator — FastAPI entrypoint.

Starts the REST API and background scheduler for:
  - heartbeat monitoring (mark offline workers)
  - task timeout + reassignment
  - stalled job recovery
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# from .models import create_tables
# from .routes import jobs, tasks, workers
# from .scheduler import build_scheduler

from coordinator.models import create_tables
from coordinator.routes import jobs, tasks, workers
from coordinator.scheduler import build_scheduler

# ─── App lifecycle ────────────────────────────────────────────────────────────

_scheduler = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    # Startup
    create_tables()
    _scheduler = build_scheduler()
    _scheduler.start()
    print("[opentrain] Coordinator started. Background scheduler running.")
    yield
    # Shutdown
    _scheduler.shutdown()
    print("[opentrain] Coordinator shut down.")


# ─── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="OpenTrain Coordinator",
    description="Distributed ML compute coordinator — schedules tasks across volunteer worker nodes.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(tasks.router)
app.include_router(workers.router)


@app.get("/", tags=["health"])
def health():
    return {
        "service": "OpenTrain Coordinator",
        "status": "ok",
        "version": "0.1.0",
    }


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok"}


# --------------------------------------------------------------------------------
# CLI / standalone startup
#
# Support running ``python -m coordinator.main`` or letting Render/uvicorn
# invoke the module directly. Render injects a PORT environment variable that
# we respect; default to 8000 for local development.
if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    print(f"[opentrain] starting uvicorn on 0.0.0.0:{port}")
    uvicorn.run("coordinator.main:app", host="0.0.0.0", port=port)
