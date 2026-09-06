"""
Backfill geolocation for previously ingested threads.

One-off (or on-demand) step that finds rows in daily_ingest which were
inserted while LLM geolocation was unavailable (no GROQ_API_KEY in the
cron), re-runs location resolution over them, and updates both the
daily_ingest.coordinates JSON blob and the thread_geo row. Re-clustering
afterwards picks up the new geo features automatically.

Run standalone:  uv run python -m worker.backfill [--limit 200] [--recluster]
Env gate:        BACKFILL_GEO_ENABLED=1 (worker main() step, default off)
"""

from __future__ import annotations

import argparse
import json
import logging
import os

import sqlalchemy as sa
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("conflux.backfill")

BACKFILL_GEO_ENABLED = os.getenv("BACKFILL_GEO_ENABLED", "0") == "1"
BACKFILL_BATCH_DEFAULT = int(os.getenv("BACKFILL_LIMIT", "200"))

# Reuse the worker geocoding stack (LLM extraction + Nominatim).
from worker.geocoding import resolve_location  # noqa: E402
from app.core import database as db  # noqa: E402


def fetch_unlocated_threads(limit: int = BACKFILL_BATCH_DEFAULT) -> list[dict]:
    """Threads in daily_ingest with no coordinates and no thread_geo row."""
    with db.engine.connect() as conn:
        rows = conn.execute(
            sa.text("""
                SELECT d.thread_id, d.title, d.content, d.subreddit
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
        {"thread_id": r[0], "title": r[1] or "", "content": r[2] or "", "source": r[3] or "reddit"}
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
        geo = resolve_location(thread["title"], thread["content"])
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


def run_backfill(limit: int = BACKFILL_BATCH_DEFAULT, recluster: bool = False) -> dict:
    """Backfill coordinates and optionally re-run clustering to pick up geo features."""
    stats = backfill_coordinates(limit)
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
    args = parser.parse_args()

    run_backfill(limit=args.limit, recluster=args.recluster)


if __name__ == "__main__":
    main()
