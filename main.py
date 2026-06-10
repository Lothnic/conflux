"""
Conflux Backend — Civic-tech AI Platform
Author: Lothnic

This module creates the FastAPI application and mounts all route modules.
Business logic lives in app/services/ and app/api/routes/.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import lifespan

app = FastAPI(
    title=settings.app_name,
    description="Civic-tech AI platform transforming citizen complaints into structured urban intelligence.",
    version=settings.app_version,
    lifespan=lifespan,
    debug=settings.debug,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ─── Mount routers ──────────────────────────────────────────────

from app.api.routes.health import router as health_router  # noqa: E402
from app.api.routes.clusters import router as clusters_router  # noqa: E402
from app.api.routes.threads import router as threads_router  # noqa: E402
from app.api.routes.proposals import router as proposals_router  # noqa: E402
from app.api.routes.research import router as research_router  # noqa: E402
from app.api.routes.ingest import router as ingest_router  # noqa: E402

app.include_router(health_router)
app.include_router(clusters_router)
app.include_router(threads_router)
app.include_router(proposals_router)
app.include_router(research_router)
app.include_router(ingest_router)


# ─── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
