"""
Service layer for thread-related database queries.
"""

from __future__ import annotations

import json
from pathlib import Path

import sqlalchemy as sa

from app.core.database import database_available, DEMO_MODE, engine
from app.services.utils import source_url
from app.services.proposal_heuristics import infer_issue_type

BASE_DIR_LOCAL = Path(__file__).resolve().parent.parent.parent
LOCAL_THREADS_FILE = BASE_DIR_LOCAL / "data" / "local_threads_geojson.json"
LOCAL_THREADS_SOURCE_FILE = BASE_DIR_LOCAL / "data" / "local_threads.json"


def fetch_latest_threads(limit: int = 50) -> list[dict]:
    if DEMO_MODE and LOCAL_THREADS_SOURCE_FILE.exists():
        with open(LOCAL_THREADS_SOURCE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        threads = payload if isinstance(payload, list) else payload.get("threads", [])

        from app.services.cluster_service import fetch_latest_clusters

        clusters = fetch_latest_clusters(50)
        cluster_by_issue: dict[str, str] = {}
        for c in clusters:
            issue = infer_issue_type(c["keywords"])
            if issue not in cluster_by_issue:
                cluster_by_issue[issue] = c["cluster_id"]

        return [
            {
                "id": t.get("id") or t.get("thread_id", ""),
                "title": t.get("title", ""),
                "url": source_url(
                    t.get("id") or t.get("thread_id", ""),
                    t.get("subreddit") or t.get("source") or "delhi",
                    t.get("url", ""),
                ),
                "author": t.get("author", "system"),
                "created_utc": t.get("created_utc") or t.get("published_at"),
                "upvotes": int(t.get("upvotes") or 0),
                "num_comments": int(t.get("num_comments") or 0),
                "flair": t.get("flair", ""),
                "content": t.get("content", ""),
                "subreddit": t.get("subreddit") or t.get("source") or "delhi",
                "lat": t.get("lat"),
                "lng": t.get("lng"),
                "cluster_id": t.get("cluster_id")
                or cluster_by_issue.get(
                    infer_issue_type(
                        f"{t.get('title', '')} {t.get('content', '')} {t.get('flair', '')}"
                    )
                ),
            }
            for t in threads[:limit]
        ]

    if not database_available():
        return []

    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("""
                SELECT d.thread_id, d.subreddit, d.title, d.content, d.flair, d.upvotes, d.published_at,
                       tg.lat, tg.lng, tcm.cluster_id, d.url, tg.location_text, tg.location_method,
                       tg.location_confidence, tg.location_precision_meters
                FROM daily_ingest d
                LEFT JOIN thread_geo tg ON d.thread_id = tg.thread_id
                LEFT JOIN thread_cluster_map tcm ON d.thread_id = tcm.thread_id
                ORDER BY d.published_at DESC
                LIMIT :lim
            """),
            {"lim": limit},
        ).fetchall()

    return [
        {
            "id": row[0],
            "title": row[2] or "",
            "url": source_url(row[0], row[1], row[10]),
            "author": "system",
            "created_utc": row[6] if row[6] else None,
            "upvotes": int(row[5] or 0),
            "num_comments": 0,
            "flair": row[4] or "",
            "content": row[3] or "",
            "subreddit": row[1] or "delhi",
            "lat": row[7],
            "lng": row[8],
            "cluster_id": row[9],
            "location_text": row[11],
            "location_method": row[12],
            "location_confidence": row[13],
            "location_precision_meters": row[14],
        }
        for row in rows
    ]
