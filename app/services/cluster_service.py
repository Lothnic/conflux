"""
Service layer for cluster-related database queries.
"""

from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa

from app.core.database import database_available, DEMO_MODE, engine
from app.services.utils import source_url

BASE_DIR_LOCAL = Path(__file__).resolve().parent.parent.parent
LOCAL_CLUSTERS_FILE = BASE_DIR_LOCAL / "data" / "local_clusters.json"


def _load_local_clusters(limit: int) -> list[dict]:
    if not LOCAL_CLUSTERS_FILE.exists():
        return []
    with open(LOCAL_CLUSTERS_FILE, "r", encoding="utf-8") as f:
        clusters = json.load(f)
    return clusters[:limit] if clusters else []


def fetch_latest_clusters(limit: int = 50) -> list[dict]:
    if DEMO_MODE:
        clusters = _load_local_clusters(limit)
        if clusters:
            return clusters

    if not database_available():
        return _load_local_clusters(limit)

    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("""
                SELECT cluster_id, cluster_label, centroid_lat, centroid_lng, size, keywords,
                       created_at, location_confidence, location_precision_meters
                FROM cluster_results
                WHERE (:include_demo = 1 OR cluster_id NOT LIKE 'demo-%')
                ORDER BY created_at DESC
                LIMIT :lim
            """),
            {"lim": limit, "include_demo": 1 if DEMO_MODE else 0},
        ).fetchall()

    if rows:
        return [
            {
                "cluster_id": r[0],
                "cluster_label": r[1],
                "centroid_lat": r[2],
                "centroid_lng": r[3],
                "size": r[4],
                "keywords": r[5],
                "created_at": r[6] if r[6] else None,
                "location_confidence": r[7],
                "location_precision_meters": r[8],
            }
            for r in rows
        ]

    return _load_local_clusters(limit)


def fetch_sources_for_cluster(cluster_id: str, limit: int = 8) -> list[dict]:
    """Fetch thread sources for a cluster from the DB."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text("""
                    SELECT d.thread_id, d.subreddit, d.title, d.url
                    FROM daily_ingest d
                    JOIN thread_cluster_map tcm ON d.thread_id = tcm.thread_id
                    WHERE tcm.cluster_id = :cid
                    LIMIT :lim
                """),
                {"cid": cluster_id, "lim": limit},
            ).fetchall()
        return [
            {
                "id": r[0],
                "subreddit": r[1] or "delhi",
                "title": r[2],
                "url": source_url(r[0], r[1], r[3]),
            }
            for r in rows
        ]
    except Exception:
        return []
