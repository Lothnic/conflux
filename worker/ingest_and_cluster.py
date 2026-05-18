"""
GitHub Actions Worker: Daily ingestion and clustering for Conflux.

This script:
1. Fetches new threads from r/delhi using Reddit's OAuth2 API
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
RATE_LIMIT_DELAY = float(os.getenv("RATE_LIMIT_DELAY", "0.5"))

# Reddit OAuth2 (get from: https://www.reddit.com/prefs/apps)
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "conflux/0.1")

# Database
DB_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/conflux")

# Embedding
MODEL_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2

# UMAP (visualization only)
UMAP_N_COMPONENTS = int(os.getenv("UMAP_N_COMPONENTS", "2"))
UMAP_N_NEIGHBORS = int(os.getenv("UMAP_N_NEIGHBORS", "15"))
UMAP_MIN_DIST = float(os.getenv("UMAP_MIN_DIST", "0.1"))

# HDBSCAN — clustering happens in FULL embedding space, NOT in 2D
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

# ============================================================
# STEP 1: Reddit Auth + Fetch
# ============================================================

def acquire_access_token() -> str:
    """Get OAuth2 access token for Reddit API."""
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        raise RuntimeError(
            "REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET env vars are required. "
            "Create an app at https://www.reddit.com/prefs/apps/"
        )
    url = "https://www.reddit.com/api/v1/access_token"
    auth = f"{REDDIT_CLIENT_ID}:{REDDIT_CLIENT_SECRET}"
    payload = {"grant_type": "client_credentials"}
    req = Request(url, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/json")
    try:
        resp = urlopen(req, timeout=15)
        data = json.loads(resp.read().decode())
        return data["access_token"]
    except HTTPError as e:
        log.error(f"Reddit auth failed: {e.code} {e.reason}")
        raise
    except URLError as e:
        log.error(f"Reddit auth network error: {e.reason}")
        raise


def fetch_new_threads() -> list[dict]:
    """Fetch new threads from subreddit using Reddit's OAuth2 API."""
    if not REDDIT_CLIENT_ID:
        log.warning("No Reddit credentials configured — generating mock data for testing.")
        return _generate_mock_threads()

    cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(hours=HOURS_BACK)

    threads = []
    access_token = acquire_access_token()

    base_url = f"https://www.reddit.com/r/{SUBREDDIT}/new.json"
    params = {"limit": "100"}
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{base_url}?{query}"

    retry_count = 0
    while retry_count < 3:
        try:
            req = Request(url, method="GET")
            req.add_header("Authorization", f"Bearer {access_token}")
            req.add_header("User-Agent", REDDIT_USER_AGENT)
            resp = urlopen(req, timeout=15)
            data = json.loads(resp.read().decode())
            break
        except HTTPError as e:
            if e.code in (429, 500, 502, 503):
                wait = 2 ** retry_count
                log.warning(f"Reddit API returned {e.code}, retrying in {wait}s...")
                time.sleep(wait)
                retry_count += 1
            else:
                log.error(f"Reddit API error: {e.code} {e.reason}")
                raise
        except URLError as e:
            log.error(f"Reddit API network error: {e.reason}")
            raise

    if retry_count >= 3:
        log.error("All retries exhausted for Reddit API.")
        raise RuntimeError("Failed to fetch Reddit threads after 3 retries")

    # Parse children
    children = data.get("data", {}).get("children", [])
    log.info(f"Reddit returned {len(children)} posts from r/{SUBREDDIT}.")

    for post_data in children:
        post = post_data.get("data", {})
        created_utc = post.get("created_utc", 0)
        created_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
        if created_dt < cutoff:
            continue

        thread_id = post.get("id", "")
        if not thread_id:
            continue

        # Dedup against DB
        if check_existing(thread_id=thread_id):
            continue

        title = post.get("title", "") or ""
        content = post.get("selftext", "") or ""
        flair = (post.get("link_flair_text") or post.get("flair_text") or "") or ""
        upvotes = post.get("score", 0) or 0

        threads.append({
            "thread_id": thread_id,
            "subreddit": SUBREDDIT,
            "title": title,
            "content": content[:50000],
            "flair": flair,
            "upvotes": upvotes,
            "published_at": created_dt,
        })

        # Rate limit: Reddit allows ~100 req/10min authenticated
        if RATE_LIMIT_DELAY > 0:
            time.sleep(RATE_LIMIT_DELAY)

    log.info(f"Fetched {len(threads)} NEW threads from Reddit (after dedup).")
    return threads


def _generate_mock_threads() -> list[dict]:
    """Generate mock threads for testing without Reddit credentials."""
    topics = [
        ("Delhi Metro expansion news", ""),
        ("Delhi pollution levels rising again", ""),
        ("Best biryani in Delhi?", ""),
        ("Delhi weather update today", ""),
        ("Delhi cricket match today", ""),
        ("Delhi traffic alert — Yamuna Expressway", ""),
        ("New café opening in South Delhi", ""),
        ("Delhi government scheme registration", ""),
        ("Delhi tech startup funding news", ""),
        ("Delhi elections updates", ""),
    ]
    threads = []
    base_time = datetime.now(timezone.utc)
    for i, (title, content) in enumerate(topics):
        threads.append({
            "thread_id": f"mock_{i}",
            "subreddit": SUBREDDIT,
            "title": title,
            "content": content,
            "flair": "",
            "upvotes": 10 + i * 3,
            "published_at": base_time - __import__("datetime").timedelta(minutes=i * 10),
        })
    return threads


# ============================================================
# STEP 2: Dedup + Bulk Insert
# ============================================================

def check_existing(thread_id: str) -> bool:
    with engine.connect() as conn:
        result = conn.execute(
            sa.text("SELECT 1 FROM daily_ingest WHERE thread_id = :tid LIMIT 1"),
            {"tid": thread_id},
        )
        return result.fetchone() is not None


def insert_batches(threads: list[dict]) -> int:
    """Bulk insert threads using executemany. Returns count of inserted rows."""
    if not threads:
        return 0

    BATCH_SIZE = 50
    total_inserted = 0

    for i in range(0, len(threads), BATCH_SIZE):
        batch = threads[i:i + BATCH_SIZE]
        with engine.begin() as conn:
            # Use executemany for batch insert
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
            # Verify insert count
            result = conn.execute(
                sa.text("SELECT COUNT(*) FROM daily_ingest")
            )
            total_inserted = result.scalar() - total_inserted  # approximate

    log.info(f"Inserted up to {len(threads)} threads into daily_ingest.")
    return total_inserted


# ============================================================
# STEP 3: Clustering (on FULL embedding space)
# ============================================================

def cluster_threads() -> list[dict]:
    """Run embedding + clustering on recently inserted threads.

    KEY FIX: Clustering uses full embedding space (384-dim),
    NOT the 2D UMAP projection used only for visualization.
    """
    # Consistent time window — use the same HOURS_BACK logic
    # We fetch all recent threads (24h is fine for a sliding window)
    with engine.connect() as conn:
        recent = conn.execute(
            sa.text(
                "SELECT thread_id, title, content FROM daily_ingest "
                "WHERE published_at >= NOW() - INTERVAL '24 HOURS' "
                "ORDER BY published_at DESC"
            )
        ).fetchall()

    if len(recent) < HDBSCAN_MIN_CLUSTER_SIZE:
        log.warning(f"Too few threads ({len(recent)}) found for clustering. Skipping.")
        return []

    log.info(f"Clustering {len(recent)} threads using full embedding space...")

    # 1) Generate embeddings (full 384-dim vectors)
    encoder = SentenceTransformer(MODEL_NAME)
    texts = [f"{row[1]} {row[2]}".strip() if row[2] else row[1] for row in recent]
    embeddings = encoder.encode(texts, show_progress_bar=True)
    embeddings = np.array(embeddings)  # shape: (N, 384)
    log.info(f"Generated embeddings: {embeddings.shape}")

    # 2) Clustering in FULL embedding space (CRITICAL FIX)
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE,
        min_samples=HDBSCAN_MIN_SAMPLES,  # was incorrectly 'eps' — this is the right param
        metric="euclidean",
        cluster_selection_epsilon=0.0,   # distance threshold for merging
        algorithm="best",
    )
    cluster_labels = clusterer.fit_predict(embeddings)
    log.info(f"HDBSCAN found {len(set(cluster_labels) - {-1})} clusters, {sum(cluster_labels == -1)} noise points.")

    # 3) Compute cluster stats using the FULL embedding centroid
    unique_labels = set(cluster_labels)
    clusters = []
    for label in unique_labels:
        if label == -1:
            continue

        mask = cluster_labels == label
        mask_indices = np.where(mask)[0]

        # Centroid in full embedding space
        centroid = embeddings[mask].mean(axis=0)

        # Keywords from member texts
        member_texts = [texts[i] for i in mask_indices]
        keywords = extract_keywords(member_texts[:20])

        clusters.append({
            "cluster_id": f"cluster_{label}",
            "cluster_label": label,
            "centroid": centroid,  # full 384-dim vector
            "centroid_lat": centroid[0],   # for DB storage (first dim only)
            "centroid_lng": centroid[1],   # for DB storage (second dim only)
            "size": int(mask.sum()),
            "member_indices": mask_indices.tolist(),
            "keywords": keywords,
        })

    # 4) Also run UMAP for visualization (NOT for clustering)
    log.info("Running UMAP for visualization (2D projection only)...")
    umap_reducer = UMAP(
        n_components=UMAP_N_COMPONENTS,
        n_neighbors=UMAP_N_NEIGHBORS,
        min_dist=UMAP_MIN_DIST,
        random_state=42,
    )
    umap_coords = umap_reducer.fit_transform(embeddings)

    # Store UMAP coordinates for visualization (optional, as JSONB)
    # ... (could add a separate table or column for this)

    # 5) Store cluster results + thread-cluster map in DB
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
                {
                    "cid": c["cluster_id"],
                    "clab": c["cluster_label"],
                    "clat": c["centroid_lat"],
                    "clng": c["centroid_lng"],
                    "sz": c["size"],
                    "kw": c["keywords"],
                },
            )
            cluster_count += 1

            # Thread-cluster mapping using UMAP coords for centroid (more interpretable)
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
    """Simple keyword extraction using word frequency."""
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
        "before", "after", "north", "south", "east", "west", "delhi", "city",
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


# ============================================================
# STEP 4: Validation
# ============================================================

def validate_results():
    """Verify pipeline outputs — sanity checks on DB state."""
    log.info("Validating pipeline results...")

    with engine.connect() as conn:
        total_threads = conn.execute(sa.text("SELECT COUNT(*) FROM daily_ingest")).scalar()
        total_clusters = conn.execute(sa.text("SELECT COUNT(*) FROM cluster_results")).scalar()
        total_mappings = conn.execute(sa.text("SELECT COUNT(*) FROM thread_cluster_map")).scalar()

    log.info(f"Post-validation: {total_threads} threads, {total_clusters} clusters, {total_mappings} mappings.")

    if total_clusters == 0:
        log.warning("No clusters found! Check HDBSCAN parameters or filter your data.")

    # Verify all clusters have members
    with engine.connect() as conn:
        orphan_clusters = conn.execute(sa.text(
            "SELECT c.cluster_id, c.cluster_label FROM cluster_results c "
            "LEFT JOIN thread_cluster_map m ON c.cluster_id = m.cluster_id "
            "WHERE m.thread_id IS NULL"
        )).fetchall()
        if orphan_clusters:
            log.warning(f"Found {len(orphan_clusters)} clusters with no members: {[c[0] for c in orphan_clusters]}")

    log.info("Validation complete.")


# ============================================================
# Main Pipeline
# ============================================================

def main():
    log.info("=" * 60)
    log.info("Starting Conflux Worker")
    log.info("=" * 60)

    try:
        # Step 1: Fetch
        log.info("--- Step 1: Fetching threads ---")
        threads = fetch_new_threads()
        if not threads:
            log.info("No new threads (already seen or fetch failed). Skipping pipeline.")
            return

        # Step 2: Insert
        log.info("--- Step 2: Inserting threads ---")
        inserted = insert_batches(threads)
        log.info(f"Inserted {inserted} new threads.")

        # Step 3: Cluster
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

        # Step 4: Validate
        log.info("--- Step 4: Validation ---")
        validate_results()

        log.info("Worker completed successfully.")

    except Exception as e:
        log.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
