"""
Service layer for cluster-related database queries.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sqlalchemy as sa

from app.core.config import settings
from app.core.database import database_available, DEMO_MODE, engine
from app.services.proposal_heuristics import infer_issue_type
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


def _trend_direction(counts: list[int]) -> tuple[int, str]:
    """Compare the most recent window against the preceding one."""
    window = max(min(3, len(counts) // 2), 1)
    recent = sum(counts[-window:])
    previous = sum(counts[-2 * window:-window])
    delta = recent - previous
    direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
    return delta, direction


def fetch_issue_trends(days: int = 14) -> dict:
    """Per-issue-type daily complaint counts over a trailing time window.

    Issue type comes from the stored LLM proposal when available, falling back
    to keyword inference on the cluster. Days with no complaints are zero-filled
    so consumers can draw continuous sparklines.
    """
    if not database_available():
        return {"days": [], "series": [], "total_recent": 0}

    days = max(2, min(int(days), 90))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    # SQLite stores UTC as 'YYYY-MM-DD HH:MM:SS'; Postgres timestamptz accepts the
    # same literal with an explicit offset.
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S") + ("" if settings.is_sqlite else " +00")

    with engine.connect() as conn:
        rows = conn.execute(
            sa.text("""
                SELECT tcm.cluster_id, d.published_at, d.created_at, cr.keywords
                FROM daily_ingest d
                JOIN thread_cluster_map tcm ON d.thread_id = tcm.thread_id
                JOIN cluster_results cr ON tcm.cluster_id = cr.cluster_id
                WHERE COALESCE(d.published_at, d.created_at) >= :cutoff
            """),
            {"cutoff": cutoff_str},
        ).fetchall()
        proposal_rows = conn.execute(
            sa.text("""
                SELECT cluster_id, issue_type FROM llm_proposals
                ORDER BY created_at DESC
            """),
        ).fetchall()

    issue_by_cluster: dict[str, str] = {}
    for cluster_id, issue_type in proposal_rows:
        if issue_type and cluster_id not in issue_by_cluster:
            issue_by_cluster[cluster_id] = issue_type

    day_list = [(cutoff + timedelta(days=i)).date().isoformat() for i in range(days)]
    day_set = set(day_list)
    per_issue: dict[str, dict[str, int]] = {}

    for cluster_id, published_at, created_at, keywords in rows:
        stamp = published_at or created_at
        if stamp is None:
            continue
        day = stamp[:10] if isinstance(stamp, str) else stamp.date().isoformat()
        if day not in day_set:
            continue
        label = issue_by_cluster.get(cluster_id) or infer_issue_type(keywords or "")
        bucket = per_issue.setdefault(label, {})
        bucket[day] = bucket.get(day, 0) + 1

    series = []
    for label in sorted(per_issue, key=lambda lbl: -sum(per_issue[lbl].values())):
        bucket = per_issue[label]
        counts = [bucket.get(day, 0) for day in day_list]
        delta, direction = _trend_direction(counts)
        series.append({
            "issue_type": label,
            "counts": counts,
            "total": sum(counts),
            "delta": delta,
            "trend": direction,
        })

    return {
        "days": day_list,
        "series": series,
        "total_recent": sum(sum(bucket.values()) for bucket in per_issue.values()),
    }


def fetch_sources_for_cluster(cluster_id: str, limit: int = 8) -> list[dict]:
    """Fetch thread sources for a cluster from the DB, freshest first."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text("""
                    SELECT d.thread_id, d.subreddit, d.title, d.url,
                           COALESCE(d.published_at, d.created_at) AS sort_date
                    FROM daily_ingest d
                    JOIN thread_cluster_map tcm ON d.thread_id = tcm.thread_id
                    WHERE tcm.cluster_id = :cid
                    ORDER BY sort_date DESC
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
                "published_at": str(r[4])[:10] if r[4] is not None else None,
            }
            for r in rows
        ]
    except Exception:
        return []
