"""
Thread-related endpoints.
"""

from fastapi import APIRouter, HTTPException

import json

from fastapi import APIRouter, HTTPException
import sqlalchemy as sa

from app.core.database import DEMO_MODE, engine, init_db_sync
from app.services.thread_service import fetch_latest_threads

router = APIRouter()


@router.get("/threads")
async def get_threads(limit: int = 50):
    """Return recent thread records for the sidebar."""
    init_db_sync()
    try:
        threads = fetch_latest_threads(limit)
        return {
            "threads": threads,
            "source": "local_demo" if DEMO_MODE else "database",
            "count": len(threads),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads/geojson")
async def get_threads_geojson(limit: int = 200):
    """Return ingested thread coordinates as GeoJSON FeatureCollection."""
    if DEMO_MODE:
        from pathlib import Path
        base = Path(__file__).resolve().parent.parent.parent.parent
        local_file = base / "data" / "local_threads_geojson.json"
        if local_file.exists():
            with open(local_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
            features = payload.get("features", [])
            if features:
                payload["features"] = features[:limit]
                return payload

    init_db_sync()

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text("""
                    SELECT tg.thread_id, tg.lat, tg.lng, tg.source, tg.created_at, tcm.cluster_id,
                           tg.location_text, tg.location_method, tg.location_confidence,
                           tg.location_precision_meters
                    FROM thread_geo tg
                    LEFT JOIN thread_cluster_map tcm ON tg.thread_id = tcm.thread_id
                    ORDER BY tg.created_at DESC
                    LIMIT :lim
                """),
                {"lim": limit},
            ).fetchall()
        features = []
        for r in rows:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [r[2], r[1]]},
                    "properties": {
                        "thread_id": r[0],
                        "source": r[3],
                        "created_at": r[4] if r[4] else None,
                        "cluster_id": r[5],
                        "location_text": r[6],
                        "location_method": r[7],
                        "location_confidence": r[8],
                        "location_precision_meters": r[9],
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
