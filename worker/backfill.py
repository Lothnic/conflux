"""
Backfill geolocation for previously ingested threads.

One-off (or on-demand) step that finds rows in daily_ingest which were
inserted while LLM geolocation was unavailable (no GROQ_API_KEY in the
cron), re-runs location resolution over them, and updates both the
daily_ingest.coordinates JSON blob and the thread_geo row. Re-clustering
afterwards picks up the new geo features automatically.

Resolution ladder per thread:
1. Title + full content through the normal LLM+geocoder path
2. Retry with a larger content window (some rows were stored truncated)
3. URL slug hints (news URLs often carry the locality, e.g.
   ".../delhi-water-crisis-lajpat-nagar-...") — slugs are matched against
   the local gazetteer and geocoded directly.

Also provides retention pruning: stale, never-geocoded, never-clustered
news/gov threads can be deleted so they stop polluting the clustering
input (cluster_threads() reads the most recent 500 rows regardless of
whether they carry any geography).

Run standalone:  uv run python -m worker.backfill [--limit 200] [--recluster]
                 uv run python -m worker.backfill --prune [--prune-days 45]
Env gate:        BACKFILL_GEO_ENABLED=1 (worker main() step, default off)
                 PRUNE_UNLOCATED_ENABLED=1 (worker main() step, default off)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from urllib.parse import unquote, urlsplit

import sqlalchemy as sa
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("conflux.backfill")

BACKFILL_GEO_ENABLED = os.getenv("BACKFILL_GEO_ENABLED", "0") == "1"
BACKFILL_BATCH_DEFAULT = int(os.getenv("BACKFILL_LIMIT", "200"))

PRUNE_UNLOCATED_ENABLED = os.getenv("PRUNE_UNLOCATED_ENABLED", "0") == "1"
PRUNE_DAYS_DEFAULT = int(os.getenv("PRUNE_UNLOCATED_DAYS", "45"))
PRUNE_BATCH_DEFAULT = int(os.getenv("PRUNE_UNLOCATED_LIMIT", "500"))

# Reuse the worker geocoding stack (LLM extraction + Nominatim).
from worker.geocoding import (
    GEOCODE_CITY,
    LOCAL_PLACE_CANDIDATES,
    geocode_text,
    resolve_location,
)  # noqa: E402
from app.core import database as db  # noqa: E402

_SLUG_SPLIT_RE = re.compile(r"[-_+/]+")


def _slug_location_candidates(url: str) -> list[str]:
    """Extract plausible Delhi place phrases from a news URL slug.

    Matches the local gazetteer first, then falls back to longer slug
    segments that look like proper nouns. Returns unique candidates,
    most-specific first.
    """
    if not url or not url.startswith("http"):
        return []
    path = unquote(urlsplit(url).path or "")
    slug = _SLUG_SPLIT_RE.sub(" ", path).lower()

    candidates: list[str] = []
    for place, _precision in LOCAL_PLACE_CANDIDATES:
        if place.lower() in slug:
            candidates.append(place)

    # Longer multi-word segments often name localities in news slugs.
    for match in re.finditer(r"[a-z][a-z]+(?: [a-z][a-z]+)+", slug):
        phrase = match.group(0).strip()
        if len(phrase) > 12 and phrase not in candidates and "news" not in phrase:
            candidates.append(phrase.title())

    return candidates[:3]


def resolve_with_hints(thread: dict) -> dict:
    """Resolve a thread's location using title/content, then URL hints."""
    title = thread.get("title", "")
    content = thread.get("content", "")

    # Attempt 1: normal path (title + stored content).
    geo = resolve_location(title, content)
    if geo.get("lat") is not None:
        return geo

    # Attempt 2: retry with a bigger content window; the stored blob may
    # mention a locality deeper than the default extraction window.
    if content and len(content) > 400:
        geo = resolve_location(title, content[:2000])
        if geo.get("lat") is not None:
            geo["location_method"] = "backfill_full_content"
            return geo

    # Attempt 3: URL slug hints against the gazetteer + geocoder.
    for candidate in _slug_location_candidates(thread.get("url", "")):
        time_guard = 1.1  # be polite to Nominatim between slug lookups
        import time as _time

        _time.sleep(time_guard)
        query = (
            candidate
            if GEOCODE_CITY.lower() in candidate.lower()
            else f"{candidate}, {GEOCODE_CITY}, India"
        )
        result = geocode_text(query)
        if result:
            return {
                "lat": result["lat"],
                "lng": result["lng"],
                "location_text": candidate,
                "location_method": "backfill_url_slug",
                "location_confidence": 0.45,
                "location_precision_meters": 900,
                "geocoder_provider": "nominatim",
                "geocoder_query": query,
                "geocoder_raw": json.dumps(result["raw"])[:4000],
            }

    return geo


def fetch_unlocated_threads(limit: int = BACKFILL_BATCH_DEFAULT) -> list[dict]:
    """Threads in daily_ingest with no coordinates and no thread_geo row."""
    with db.engine.connect() as conn:
        rows = conn.execute(
            sa.text("""
                SELECT d.thread_id, d.title, d.content, d.subreddit, d.url
                FROM daily_ingest d
                LEFT JOIN thread_geo tg ON d.thread_id = tg.thread_id
                WHERE tg.thread_id IS NULL
                   OR (tg.lat IS NULL AND tg.lng IS NULL)
                ORDER BY d.published_at DESC
                LIMIT :lim
            """),
            {"lim": limit},
        ).fetchall()
    return [
        {
            "thread_id": r[0],
            "title": r[1] or "",
            "content": r[2] or "",
            "source": r[3] or "reddit",
            "url": r[4] or "",
        }
        for r in rows
    ]


def backfill_coordinates(limit: int = BACKFILL_BATCH_DEFAULT) -> dict:
    """Re-geocode unlocated threads; returns counters for logging."""
    threads = fetch_unlocated_threads(limit)
    if not threads:
        log.info("Backfill: no unlocated threads found. Nothing to do.")
        return {"candidates": 0, "resolved": 0, "failed": 0}

    log.info("Backfill: re-geocoding %d thread(s)...", len(threads))
    resolved = 0
    failed = 0

    for thread in threads:
        geo = resolve_with_hints(thread)
        lat, lng = geo.get("lat"), geo.get("lng")

        with db.engine.begin() as conn:
            if lat is not None and lng is not None:
                resolved += 1
                coords = json.dumps({
                    "lat": float(lat),
                    "lng": float(lng),
                    "location_text": geo.get("location_text", ""),
                    "location_method": geo.get("location_method", ""),
                    "location_confidence": geo.get("location_confidence"),
                    "location_precision_meters": geo.get("location_precision_meters"),
                })
                conn.execute(
                    sa.text("""
                        UPDATE daily_ingest
                        SET coordinates = :coords
                        WHERE thread_id = :tid
                    """),
                    {"coords": coords, "tid": thread["thread_id"]},
                )
            else:
                failed += 1

            conn.execute(
                sa.text("""
                    INSERT INTO thread_geo
                        (thread_id, lat, lng, source, location_text, location_method,
                         location_confidence, location_precision_meters, geocoder_provider,
                         geocoder_query, geocoder_raw)
                    VALUES (:tid, :lat, :lng, :src,
                            :loctext, :method, :conf, :precision, 'nominatim', :query, :raw)
                    ON CONFLICT (thread_id) DO UPDATE SET
                        lat = EXCLUDED.lat,
                        lng = EXCLUDED.lng,
                        location_text = EXCLUDED.location_text,
                        location_method = EXCLUDED.location_method,
                        location_confidence = EXCLUDED.location_confidence,
                        location_precision_meters = EXCLUDED.location_precision_meters,
                        geocoder_provider = EXCLUDED.geocoder_provider,
                        geocoder_query = EXCLUDED.geocoder_query,
                        geocoder_raw = EXCLUDED.geocoder_raw
                """),
                {
                    "tid": thread["thread_id"],
                    "lat": lat,
                    "lng": lng,
                    "src": thread.get("source", "reddit"),
                    "loctext": geo.get("location_text", ""),
                    "method": geo.get("location_method", "backfill"),
                    "conf": geo.get("location_confidence"),
                    "precision": geo.get("location_precision_meters"),
                    "query": geo.get("geocoder_query", ""),
                    "raw": (geo.get("geocoder_raw") or "")[:4000],
                },
            )

    log.info(
        "Backfill complete: %d resolved, %d still unresolved (of %d candidates).",
        resolved, failed, len(threads),
    )
    return {"candidates": len(threads), "resolved": resolved, "failed": failed}


# ─── Retention pruning ───────────────────────────────────────────

_PRUNABLE_SOURCES = ("news:", "gov:")  # non-interactive sources only


def prune_unlocated_threads(
    older_than_days: int = PRUNE_DAYS_DEFAULT,
    limit: int = PRUNE_BATCH_DEFAULT,
) -> dict:
    """Delete stale threads that carry no geography and never joined a
    geocoded cluster.

    A thread is prunable when ALL of these hold:
    - older than ``older_than_days``
    - no thread_geo coordinates (or NULL lat/lng)
    - not mapped to any cluster that has a centroid (those clusters are
      the product; unlocated noise that never fed a located cluster is
      what dilutes the HDBSCAN input)
    - source is news/gov (never user complaints)

    Returns counters; respects ``limit`` so one run cannot nuke
    unbounded rows.
    """
    from datetime import datetime, timedelta, timezone
    from app.core.config import settings

    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).strftime("%Y-%m-%d %H:%M:%S")
    if not settings.is_sqlite:
        cutoff += " +00"

    with db.engine.connect() as conn:
        rows = conn.execute(
            sa.text("""
                SELECT d.thread_id
                FROM daily_ingest d
                LEFT JOIN thread_geo tg ON d.thread_id = tg.thread_id
                LEFT JOIN thread_cluster_map tcm ON d.thread_id = tcm.thread_id
                LEFT JOIN cluster_results cr ON tcm.cluster_id = cr.cluster_id
                WHERE (d.subreddit LIKE 'news:%' OR d.subreddit LIKE 'gov:%')
                  AND d.published_at < :cutoff
                  AND (tg.thread_id IS NULL OR (tg.lat IS NULL AND tg.lng IS NULL))
                  AND (
                        tcm.thread_id IS NULL
                        OR cr.cluster_id IS NULL
                        OR cr.centroid_lat IS NULL
                      )
                LIMIT :lim
            """),
            {"cutoff": cutoff, "lim": limit},
        ).fetchall()

    thread_ids = [r[0] for r in rows]
    if not thread_ids:
        log.info("Prune: no prunable unlocated threads older than %dd.", older_than_days)
        return {"candidates": 0, "deleted": 0}

    deleted = 0
    for chunk_start in range(0, len(thread_ids), 100):
        chunk = thread_ids[chunk_start:chunk_start + 100]
        with db.engine.begin() as conn:
            # Children first: thread_cluster_map has an FK to daily_ingest.
            conn.execute(
                sa.text("DELETE FROM thread_cluster_map WHERE thread_id IN :tids")
                .bindparams(sa.bindparam("tids", expanding=True)),
                {"tids": chunk},
            )
            conn.execute(
                sa.text("DELETE FROM thread_geo WHERE thread_id IN :tids")
                .bindparams(sa.bindparam("tids", expanding=True)),
                {"tids": chunk},
            )
            result = conn.execute(
                sa.text("DELETE FROM daily_ingest WHERE thread_id IN :tids")
                .bindparams(sa.bindparam("tids", expanding=True)),
                {"tids": chunk},
            )
            deleted += result.rowcount or 0

    log.info(
        "Prune: deleted %d/%d stale unlocated thread(s) older than %dd.",
        deleted, len(thread_ids), older_than_days,
    )
    return {"candidates": len(thread_ids), "deleted": deleted}


def run_backfill(
    limit: int = BACKFILL_BATCH_DEFAULT,
    recluster: bool = False,
    prune: bool = False,
    prune_days: int = PRUNE_DAYS_DEFAULT,
) -> dict:
    """Backfill coordinates, optionally prune dead threads and re-cluster."""
    if prune:
        prune_stats = prune_unlocated_threads(older_than_days=prune_days)
    else:
        prune_stats = None

    stats = backfill_coordinates(limit)
    if prune_stats:
        stats["pruned"] = prune_stats
    if recluster and stats["resolved"] > 0:
        from worker.clustering import cluster_threads

        log.info("Backfill: re-running clustering to absorb new geo features...")
        clusters = cluster_threads()
        log.info("Backfill: clustering produced %d cluster(s).", len(clusters))
    return stats


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Backfill geolocation for unlocated threads.")
    parser.add_argument("--limit", type=int, default=BACKFILL_BATCH_DEFAULT,
                        help=f"Max threads to process (default {BACKFILL_BATCH_DEFAULT})")
    parser.add_argument("--recluster", action="store_true",
                        help="Re-run HDBSCAN clustering after backfilling")
    parser.add_argument("--prune", action="store_true",
                        help="Delete stale unlocated news/gov threads before backfilling")
    parser.add_argument("--prune-days", type=int, default=PRUNE_DAYS_DEFAULT,
                        help=f"Age threshold for pruning (default {PRUNE_DAYS_DEFAULT})")
    args = parser.parse_args()

    run_backfill(limit=args.limit, recluster=args.recluster,
                 prune=args.prune, prune_days=args.prune_days)


if __name__ == "__main__":
    main()
