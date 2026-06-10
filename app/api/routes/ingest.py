"""
Ingestion and clustering trigger endpoints.
"""

from __future__ import annotations

import json
from uuid import uuid4

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException

from app.core.database import engine, init_db_sync
from app.core.models import ComplainList

router = APIRouter()


@router.post("/ingest")
async def ingest_complaints(data: ComplainList):
    """Ingest a batch of multilingual citizen complaints."""
    if not init_db_sync():
        raise HTTPException(status_code=503, detail="Database is unavailable")

    inserted = 0
    with engine.begin() as conn:
        for c in data.complaints:
            thread_id = uuid4().hex[:32]
            coords = json.dumps({"lat": float(c.lat), "lng": float(c.lon)})
            conn.execute(
                sa.text("""
                    INSERT INTO daily_ingest
                    (thread_id, subreddit, title, content, flair, upvotes, coordinates, published_at)
                    VALUES (:tid, :sub, :title, :content, :flair, :upv, :coords, CURRENT_TIMESTAMP)
                    ON CONFLICT (thread_id) DO NOTHING
                """),
                {
                    "tid": thread_id,
                    "sub": c.source or "manual",
                    "title": "",
                    "content": c.text,
                    "flair": c.language,
                    "upv": 0,
                    "coords": coords,
                },
            )
            conn.execute(
                sa.text("""
                    INSERT INTO thread_geo (thread_id, lat, lng, source)
                    VALUES (:tid, :lat, :lng, :src)
                    ON CONFLICT (thread_id) DO NOTHING
                """),
                {
                    "tid": thread_id,
                    "lat": float(c.lat),
                    "lng": float(c.lon),
                    "src": c.source or "manual",
                },
            )
            inserted += 1
    return {"status": "ok", "ingested": inserted}


@router.post("/cluster")
async def cluster_complaints():
    """Run clustering on ingested complaints."""
    if not init_db_sync():
        raise HTTPException(status_code=503, detail="Database is unavailable")

    try:
        from worker.clustering import cluster_threads
        clusters = cluster_threads()
        return {
            "status": "ok",
            "message": "Clustering complete",
            "clusters": len(clusters),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
