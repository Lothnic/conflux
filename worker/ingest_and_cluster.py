"""
GitHub Actions Worker: Daily ingestion and clustering for Conflux.

This is a thin entry point that orchestrates the modular worker components:
- worker.ingest: Multi-source data fetching (Reddit, RSS, open data)
- worker.geocoding: Location resolution and geocoding
- worker.clustering: Embedding + HDBSCAN clustering

Run locally: uv run worker/ingest_and_cluster.py
Deploy on: GitHub Actions (daily cron, see .github/workflows/)
"""

import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Add parent dir to path for shared app package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---- Logging ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("conflux.worker")

DEMO_MODE = os.getenv("CONFLUX_DEMO", "0") == "1"
BACKFILL_GEO_ENABLED = os.getenv("BACKFILL_GEO_ENABLED", "0") == "1"
PRUNE_UNLOCATED_ENABLED = os.getenv("PRUNE_UNLOCATED_ENABLED", "0") == "1"

# Import modular components
from app.core import database as db
from worker.ingest import (
    fetch_new_threads,
    fetch_news_threads,
    fetch_opendata_threads,
    fetch_gdelt_threads,
    build_demo_threads,
)
from worker.clustering import (
    cluster_threads,
    build_demo_clusters,
    write_local_artifacts,
    validate_results,
    insert_batches,
)


def main():
    log.info("=" * 60)
    log.info("Starting Conflux Worker")
    log.info("=" * 60)

    try:
        if DEMO_MODE or not db.database_available():
            log.warning("Database unavailable. Writing local demo artifacts instead.")
            threads = build_demo_threads()
            clusters = build_demo_clusters(threads)
            write_local_artifacts(threads, clusters)
            log.info(f"Wrote {len(threads)} demo threads and {len(clusters)} demo clusters.")
            log.info("Worker completed successfully in local demo mode.")
            return

        db.create_tables()
        log.info("--- Step 1: Fetching civic reports (news RSS + Google News + GDELT + open data; Reddit optional) ---")
        threads = fetch_new_threads()
        threads += fetch_news_threads()
        threads += fetch_gdelt_threads()
        threads += fetch_opendata_threads()
        if not threads:
            log.info("No new threads (already seen or fetch failed). Skipping pipeline.")
            return
        by_source: dict[str, int] = {}
        for t in threads:
            by_source[t.get("source", "reddit")] = by_source.get(t.get("source", "reddit"), 0) + 1
        log.info(f"Fetched {len(threads)} threads across sources: {by_source}")

        log.info("--- Step 2: Inserting threads ---")
        inserted = insert_batches(threads)
        log.info(f"Inserted {inserted} new threads.")

        log.info("--- Step 2.5: Backfilling geolocation for old unlocated threads ---")
        if BACKFILL_GEO_ENABLED or PRUNE_UNLOCATED_ENABLED:
            from worker.backfill import run_backfill

            stats = run_backfill(prune=PRUNE_UNLOCATED_ENABLED)
            log.info("Backfill stats: %s", stats)
        else:
            log.info("Backfill disabled (set BACKFILL_GEO_ENABLED=1 to enable).")

        log.info("--- Step 3: Clustering ---")
        clusters = cluster_threads()
        if clusters:
            log.info(f"Found {len(clusters)} clusters:")
            for c in clusters:
                log.info(
                    f"  Cluster {c['cluster_label']:>3} -> {c['size']:>4} threads, "
                    f"keywords: {c['keywords']}"
                )
        else:
            log.warning("No clusters found — threads may be too sparse or too few.")

        log.info("--- Step 4: Validation ---")
        validate_results()

        log.info("--- Step 5: Proposal Generation ---")
        from app.services.proposal_generator import generate_proposal_for_cluster, store_proposal
        import sqlalchemy as sa
        for c in clusters:
            with db.engine.connect() as conn:
                member_rows = conn.execute(
                    sa.text("""
                        SELECT d.thread_id, d.subreddit, d.title, d.content, d.upvotes
                        FROM daily_ingest d
                        JOIN thread_cluster_map tcm ON d.thread_id = tcm.thread_id
                        WHERE tcm.cluster_id = :cid
                    """),
                    {"cid": c["cluster_id"]},
                ).fetchall()
            member_threads = [
                {"thread_id": r[0], "subreddit": r[1], "title": r[2], "content": r[3], "upvotes": r[4]}
                for r in member_rows
            ]
            proposal = generate_proposal_for_cluster(
                c["cluster_id"], c["keywords"], c["size"],
                c.get("centroid_lat"), c.get("centroid_lng"),
                member_threads
            )
            if proposal:
                store_proposal(db.engine, proposal)
            else:
                log.warning(f"No LLM proposal generated for cluster {c['cluster_id']}")

        log.info("Worker completed successfully.")

    except Exception as e:
        log.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
