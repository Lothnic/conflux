"""
GitHub Actions Worker: Daily ingestion and clustering for Conflux.

This script:
1. Fetches new threads from r/delhi using Reddit's public JSON API (no auth required)
2. Runs embeddings + UMAP + HDBSCAN clustering on full embedding space
3. Stores results in Neon/Postgres via SQLAlchemy
4. Deduplicates by Reddit thread_id
5. Validates pipeline outputs

Run locally: uv run worker/ingest_and_cluster.py
Deploy on: GitHub Actions (cron every 4 hours, see .github/workflows/)
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import numpy as np
import pandas as pd
import sqlalchemy as sa
from umap import UMAP
import hdbscan
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

# Load .env files automatically (local or CI)
load_dotenv()

# ---- Logging ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("conflux.worker")

# ---- Config ----
SUBREDDIT = os.getenv("SUBREDDIT", "delhi")
HOURS_BACK = int(os.getenv("HOURS_BACK", "4"))
RATE_LIMIT_DELAY = float(os.getenv("RATE_LIMIT_DELAY", "60.0"))  # Public API limit ~1 req/min

# Reddit OAuth2 (optional, public API works without these)
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "conflux/0.1")

# Database
DB_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/conflux")
if DB_URL == "postgresql://localhost:5432/conflux":
    log.warning("DATABASE_URL not set in .env or secrets. Falling back to localhost.")

# Embedding
MODEL_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2

# UMAP (visualization only)
UMAP_N_COMPONENTS = int(os.getenv("UMAP_N_COMPONENTS", "2"))
UMAP_N_NEIGHBORS = int(os.getenv("UMAP_N_NEIGHBORS", "15"))
UMAP_MIN_DIST = float(os.getenv("UMAP_MIN_DIST", "0.1"))

# HDBSCAN
HDBSCAN_MIN_CLUSTER_SIZE = int(os.getenv("HDBSCAN_MIN_CLUSTER_SIZE", "3"))
HDBSCAN_MIN_SAMPLES = int(os.getenv("HDBSCAN_MIN_SAMPLES", "5"))

# ---- DB Setup ----
engine = sa.create_engine(DB_URL, pool_pre_ping=True)

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS daily_ingest (
    thread_id     VARCHAR(32) PRIMARY KEY,
    subreddit     VARCHAR,
    title         TEXT,
    content       TEXT,
    flair         VARCHAR,
    upvotes       INT,
    coordinates   JSONB,
    published_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cluster_results (
    cluster_id    VARCHAR PRIMARY KEY,
    cluster_label INT,
    centroid_lat  FLOAT,
    centroid_lng  FLOAT,
    size          INT,
    keywords      TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS thread_cluster_map (
    thread_id     VARCHAR REFERENCES daily_ingest(thread_id),
    cluster_id    VARCHAR REFERENCES cluster_results(cluster_id),
    PRIMARY KEY (thread_id, cluster_id)
);
"""


def create_tables():
    """Ensure tables exist before any operation."""
    with engine.begin() as conn:
        for stmt in CREATE_TABLES_SQL.strip().split(';'):
            if stmt.strip():
                log.info(f"Running DDL: {stmt.strip()[:50]}...")
                conn.execute(sa.text(stmt))
    log.info("Database tables verified/created.")


# ====================================================
# STEP 1: Reddit Fetch (Public JSON / Authenticated)
# ====================================================

def fetch_new_threads() -> list[dict]:
    """Fetch new threads from subreddit. Falls back to public API if no OAuth keys."""
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        log.info("No Reddit OAuth keys provided. Using public /r/{sub}/new.json endpoint.")
        return _fetch_public_threads()

    log.info("Using Reddit OAuth2 API.")
    access_token = acquire_access_token()
    cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(hours=HOURS_BACK)

    base_url = f"https://www.reddit.com/r/{SUBREDDIT}/new.json"
    query = "limit=100"
    url = f"{base_url}?{query}"

    threads = []
    for attempt in range(3):
        try:
            req = Request(url, method="GET")
            req.add_header("Authorization", f"Bearer {access_token}")
            req.add_header("User-Agent", REDDIT_USER_AGENT)
            resp = urlopen(req, timeout=15)
            data = json.loads(resp.read().decode())
            break
        except HTTPError as e:
            wait = 2 ** attempt
            log.warning(f"Reddit API error {e.code}, retrying in {wait}s...")
            time.sleep(wait)
        except URLError as e:
            log.error(f"Network error: {e.reason}")
            time.sleep(5)

    else:
        log.error("All retries failed for OAuth fetch. Falling back to public API.")
        return _fetch_public_threads()

    children = data.get("data", {}).get("children", [])
    log.info(f"OAuth fetch returned {len(children)} posts from r/{SUBREDDIT}.")

    for post_data in children:
        post = post_data.get("data", {})
        created_utc = post.get("created_utc", 0)
        created_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
        if created_dt < cutoff:
            continue
        thread_id = post.get("id", "")
        if not thread_id or check_existing(thread_id):
            continue

        threads.append({
            "thread_id": thread_id,
            "subreddit": SUBREDDIT,
            "title": post.get("title", ""),
            "content": post.get("selftext", ""),
            "flair": post.get("link_flair_text", "") or "",
            "upvotes": post.get("score", 0),
            "published_at": created_dt,
        })
        time.sleep(RATE_LIMIT_DELAY)

    return threads


def _fetch_public_threads() -> list[dict]:
    """Fetch threads using Reddit's free, unauthenticated JSON endpoint."""
    cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(hours=HOURS_BACK)
    public_url = f"https://old.reddit.com/r/{SUBREDDIT}/new.json?limit=50"
    
    # Respect public API rate limits
    time.sleep(60)

    threads = []
    try:
        req = Request(public_url, method="GET")
        req.add_header("User-Agent", "conflux/0.1 (anonymous)")
        resp = urlopen(req, timeout=15)
        data = json.loads(resp.read().decode())
    except (HTTPError, URLError, json.JSONDecodeError) as e:
        log.error(f"Public Reddit fetch failed: {e}")
        return []

    for post_data in data.get("data", {}).get("children", []):
        post = post_data.get("data", {})
        created_utc = post.get("created_utc", 0)
        created_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
        if created_dt < cutoff:
            continue
        thread_id = post.get("id", "")
        if not thread_id or check_existing(thread_id):
            continue

        threads.append({
            "thread_id": thread_id,
            "subreddit": SUBREDDIT,
            "title": post.get("title", ""),
            "content": post.get("selftext", ""),
            "flair": post.get("link_flair_text", "") or "",
            "upvotes": post.get("score", 0),
            "published_at": created_dt,
        })

    log.info(f"Public API fetch returned {len(threads)} new threads.")
    return threads


def acquire_access_token() -> str:
    """Optional: Get OAuth2 access token if credentials are provided."""
    url = "https://www.reddit.com/api/v1/access_token"
    auth = f"{REDDIT_CLIENT_ID}:{REDDIT_CLIENT_SECRET}"
    payload = {"grant_type": "client_credentials"}
    req = Request(url, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/json")
    resp = urlopen(req, timeout=15)
    return json.loads(resp.read().decode())["access_token"]


# ====================================================
# STEP 2: Dedup + Bulk Insert
# ====================================================

def check_existing(thread_id: str) -> bool:
    with engine.connect() as conn:
        result = conn.execute(
            sa.text("SELECT 1 FROM daily_ingest WHERE thread_id = :tid LIMIT 1"),
            {"tid": thread_id},
        )
        return result.fetchone() is not None


def insert_batches(threads: list[dict]) -> int:
    if not threads:
        return 0
    BATCH_SIZE = 50
    total_inserted = 0
    for i in range(0, len(threads), BATCH_SIZE):
        batch = threads[i:i + BATCH_SIZE]
        with engine.begin() as conn:
            conn.execute(
                sa.text("""
                    INSERT INTO daily_ingest
                    (thread_id, subreddit, title, content, flair, upvotes, published_at)
                    VALUES (:tid, :sub, :title, :content, :flair, :upv, :pub)
                    ON CONFLICT (thread_id) DO NOTHING
                """),
                [{"tid": t["thread_id"], "sub": t["subreddit"], "title": t["title"],
                  "content": t["content"], "flair": t["flair"], "upv": t["upvotes"],
                  "pub": t["published_at"]} for t in batch],
            )
    log.info(f"Inserted {len(threads)} threads into daily_ingest.")
    return len(threads)


# ====================================================
# STEP 3: Clustering (on FULL embedding space)
# ====================================================

def cluster_threads() -> list[dict]:
    with engine.connect() as conn:
        recent = conn.execute(
            sa.text("SELECT thread_id, title, content FROM daily_ingest "
                    "WHERE published_at >= NOW() - INTERVAL '24 HOURS' "
                    "ORDER BY published_at DESC")
        ).fetchall()

    if len(recent) < HDBSCAN_MIN_CLUSTER_SIZE:
        log.warning(f"Too few threads ({len(recent)}) found for clustering. Skipping.")
        return []

    log.info(f"Clustering {len(recent)} threads using full embedding space...")

    encoder = SentenceTransformer(MODEL_NAME)
    texts = [f"{row[1]} {row[2]}".strip() if row[2] else row[1] for row in recent]
    embeddings = encoder.encode(texts, show_progress_bar=True)
    embeddings = np.array(embeddings)
    log.info(f"Generated embeddings: {embeddings.shape}")

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE,
        min_samples=HDBSCAN_MIN_SAMPLES,
        metric="euclidean",
        cluster_selection_epsilon=0.0,
        algorithm="best",
    )
    cluster_labels = clusterer.fit_predict(embeddings)
    log.info(f"HDBSCAN found {len(set(cluster_labels) - {-1})} clusters, {sum(cluster_labels == -1)} noise points.")

    unique_labels = set(cluster_labels)
    clusters = []
    for label in unique_labels:
        if label == -1:
            continue
        mask = cluster_labels == label
        mask_indices = np.where(mask)[0]
        centroid = embeddings[mask].mean(axis=0)
        member_texts = [texts[i] for i in mask_indices]
        keywords = extract_keywords(member_texts[:20])

        clusters.append({
            "cluster_id": f"cluster_{label}",
            "cluster_label": label,
            "centroid_lat": centroid[0],
            "centroid_lng": centroid[1],
            "size": int(mask.sum()),
            "member_indices": mask_indices.tolist(),
            "keywords": keywords,
        })

    log.info("Running UMAP for visualization (2D projection only)...")
    umap_reducer = UMAP(n_components=UMAP_N_COMPONENTS, n_neighbors=UMAP_N_NEIGHBORS, min_dist=UMAP_MIN_DIST, random_state=42)
    umap_coords = umap_reducer.fit_transform(embeddings)

    cluster_count = 0
    mapping_count = 0
    with engine.begin() as conn:
        for c in clusters:
            conn.execute(
                sa.text("""
                    INSERT INTO cluster_results
                    (cluster_id, cluster_label, centroid_lat, centroid_lng, size, keywords)
                    VALUES (:cid, :clab, :clat, :clng, :sz, :kw)
                    ON CONFLICT (cluster_id) DO NOTHING
                """),
                {"cid": c["cluster_id"], "clab": c["cluster_label"], "clat": c["centroid_lat"],
                 "clng": c["centroid_lng"], "sz": c["size"], "kw": c["keywords"]},
            )
            cluster_count += 1
            umap_centroid = umap_coords[c["member_indices"]].mean(axis=0)
            for idx in c["member_indices"]:
                thread_id = recent[idx][0]
                conn.execute(
                    sa.text("""
                        INSERT INTO thread_cluster_map (thread_id, cluster_id)
                        VALUES (:tid, :cid)
                        ON CONFLICT (thread_id, cluster_id) DO NOTHING
                    """),
                    {"tid": thread_id, "cid": c["cluster_id"]},
                )
                mapping_count += 1

    log.info(f"Wrote {cluster_count} clusters and {mapping_count} thread-cluster mappings.")
    return clusters


def extract_keywords(texts, n=5):
    import re
    from collections import Counter
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "will", "can", "could", "would", "should",
        "may", "might", "shall", "must", "and", "or", "not", "but", "if",
        "then", "else", "when", "where", "why", "how", "what", "which",
        "who", "whom", "this", "that", "these", "those", "it", "its", "there",
        "here", "now", "so", "such", "with", "without", "for", "from", "in",
        "on", "at", "to", "of", "about", "between", "through", "during",
        "before", "after", "north", "south", "east", "west", "city",
        "govt", "government", "people", "many", "much", "some", "any", "one",
        "each", "every", "both", "few", "more", "most", "other", "same",
        "than", "too", "very", "just", "also", "only", "own", "over", "under",
    }
    words = []
    for text in texts:
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", text.lower())
        words.extend(w for w in cleaned.split() if w not in stop_words and len(w) > 2)
    counter = Counter(words)
    return " ".join(word for word, _ in counter.most_common(n))


# ====================================================
# STEP 4: Validation
# ====================================================

def validate_results():
    log.info("Validating pipeline results...")
    with engine.connect() as conn:
        total_threads = conn.execute(sa.text("SELECT COUNT(*) FROM daily_ingest")).scalar()
        total_clusters = conn.execute(sa.text("SELECT COUNT(*) FROM cluster_results")).scalar()
        total_mappings = conn.execute(sa.text("SELECT COUNT(*) FROM thread_cluster_map")).scalar()
    log.info(f"Post-validation: {total_threads} threads, {total_clusters} clusters, {total_mappings} mappings.")
    if total_clusters == 0:
        log.warning("No clusters found! Check HDBSCAN parameters or filter your data.")
    log.info("Validation complete.")


# ====================================================
# Main Pipeline
# ====================================================

def main():
    log.info("=" * 60)
    log.info("Starting Conflux Worker")
    log.info("=" * 60)

    try:
        create_tables()
        log.info("--- Step 1: Fetching threads ---")
        threads = fetch_new_threads()
        if not threads:
            log.info("No new threads (already seen or fetch failed). Skipping pipeline.")
            return

        log.info("--- Step 2: Inserting threads ---")
        inserted = insert_batches(threads)
        log.info(f"Inserted {inserted} new threads.")

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
        log.info("Worker completed successfully.")

    except Exception as e:
        log.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()