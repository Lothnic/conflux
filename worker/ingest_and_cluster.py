"""
Render Cron Worker: Daily ingestion and clustering for Conflux.

This script:
1. Fetches new threads from r/delhi using PRAW
2. Runs UMAP + HDBSCAN clustering
3. Stores results in Neon/Postgres via SQLAlchemy
4. Deduplicates by Reddit thread_id

Run locally: uv run worker/ingest_and_cluster.py
Deploy on: Render Cron Job (runs every 4 hours)
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import praw
import numpy as np
import pandas as pd
import sqlalchemy as sa
from umap import UMAP
import hdbscan
from sentence_transformers import SentenceTransformer

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("conflux.worker")

# --- Config ---
REDDIT_CREDS = {
    "client_id": os.getenv("REDDIT_CLIENT_ID", ""),
    "client_secret": os.getenv("REDDIT_CLIENT_SECRET"),
    "user_agent": "Conflux:Cron:1.0",
}

SUBREDDIT = os.getenv("SUBREDDIT", "delhi")
HOURS_BACK = int(os.getenv("HOURS_BACK", "4"))

DB_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/conflux")

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

UMAP_N_COMPONENTS = int(os.getenv("UMAP_N_COMPONENTS", "2"))
UMAP_N_NEIGHBORS = int(os.getenv("UMAP_N_NEIGHBORS", "15"))
UMAP_MIN_DIST = float(os.getenv("UMAP_MIN_DIST", "0.1"))

HDBSCAN_MIN_CLUSTER_SIZE = int(os.getenv("HDBSCAN_MIN_CLUSTER_SIZE", "3"))
HDBSCAN_EPS = float(os.getenv("HDBSCAN_EPS", "0.5"))

# --- DB Setup ---
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

log.info("Connecting to database...")
with engine.begin() as conn:
    conn.execute(sa.text(CREATE_TABLES_SQL))
log.info("Database tables ready.")

# --- PRAW Fetcher ---
def get_praw_client() -> praw.reddit.Reddit:
    return praw.Reddit(
        client_id=REDDIT_CREDS["client_id"],
        client_secret=REDDIT_CREDS["client_secret"],
        user_agent=REDDIT_CREDS["user_agent"],
    )

def fetch_new_threads() -> list[dict]:
    """Fetch new threads from r/delhi published in the last N hours."""
    client = get_praw_client()
    sub = client.subreddit(SUBREDDIT)
    cutoff = datetime.now(timezone.utc).timestamp() - (HOURS_BACK * 3600)
    
    threads = []
    log.info(f"Fetching threads from r/{SUBREDDIT} (last {HOURS_BACK} hours)...")
    
    for post in sub.new(limit=50):
        if post.created_utc < cutoff:
            continue
        
        # Skip self-posts without flairs or already ingested
        # Check for duplicates in DB
        already_exists = check_existing(thread_id=post.id)
        if already_exists:
            continue
            
        thread_id = post.id
        title = post.title or ""
        content = post.selftext or ""
        flair = post.link_flair_text or ""
        upvotes = post.score or 0
        
        threads.append({
            "thread_id": thread_id,
            "subreddit": SUBREDDIT,
            "title": title,
            "content": content[:50000],  # Truncate very long content
            "flair": flair,
            "upvotes": upvotes,
            "coordinates": None,  # Will be filled by geocoder or mock
            "published_at": datetime.fromtimestamp(post.created_utc, tz=timezone.utc),
        })
    
    log.info(f"Fetched {len(threads)} new threads.")
    return threads

# --- Deduplication ---
def check_existing(thread_id: str) -> bool:
    with engine.connect() as conn:
        result = conn.execute(
            sa.text("SELECT 1 FROM daily_ingest WHERE thread_id = :tid LIMIT 1"),
            {"tid": thread_id}
        )
        return result.fetchone() is not None

def insert_batches(threads: list[dict]):
    """Insert threads in batches to avoid massive single queries."""
    BATCH_SIZE = 20
    
    for i in range(0, len(threads), BATCH_SIZE):
        batch = threads[i:i+BATCH_SIZE]
        with engine.begin() as conn:
            for t in batch:
                coords_str = json.dumps(t["coordinates"]) if t["coordinates"] else "null"
                conn.execute(
                    sa.text("""
                        INSERT INTO daily_ingest 
                        (thread_id, subreddit, title, content, flair, upvotes, coordinates, published_at)
                        VALUES (:tid, :sub, :title, :content, :flair, :upv, :coords, :pub)
                        ON CONFLICT (thread_id) DO NOTHING
                    """),
                    {
                        "tid": t["thread_id"],
                        "sub": t["subreddit"],
                        "title": t["title"],
                        "content": t["content"],
                        "flair": t["flair"],
                        "upv": t["upvotes"],
                        "coords": coords_str,
                        "pub": t["published_at"],
                    }
                )
    log.info(f"Inserted {len(threads)} threads in batches.")

# --- Clustering ---
def cluster_threads() -> list[dict]:
    """Run UMAP + HDBSCAN on the last N hours of threads."""
    with engine.connect() as conn:
        recent = conn.execute(
            sa.text(f"SELECT title, content, published_at FROM daily_ingest WHERE published_at >= NOW() - INTERVAL '24 HOURS'")
        ).fetchall()
    
    if len(recent) < HDBSCAN_MIN_CLUSTER_SIZE:
        log.warning(f"Too few threads ({len(recent)}) found for clustering. Skipping.")
        return []
    
    log.info(f"Clustering {len(recent)} threads...")
    texts = [f"{row[0]} {row[1]}" for row in recent]
    
    # Generate embeddings
    encoder = SentenceTransformer(MODEL_NAME)
    embeddings = encoder.encode(texts, show_progress_bar=True)
    embeddings = np.array(embeddings)
    
    # UMAP dimensionality reduction
    umap = UMAP(
        n_components=UMAP_N_COMPONENTS,
        n_neighbors=UMAP_N_NEIGHBORS,
        min_dist=UMAP_MIN_DIST,
        random_state=42,
    )
    reduced = umap.fit_transform(embeddings)
    
    # HDBSCAN clustering
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE,
        eps=HDBSCAN_EPS,
        algorithm="best",
        metric="euclidean",
    )
    cluster_labels = clusterer.fit_predict(reduced)
    
    # Get cluster stats
    unique_labels = set(cluster_labels)
    clusters = []
    for label in unique_labels:
        if label == -1:
            continue  # Skip noise points
        
        mask = cluster_labels == label
        label_texts = [texts[i] for i in range(len(texts)) if mask[i]]
        
        # Compute centroid
        centroid_lat = reduced[mask, 0].mean()
        centroid_lng = reduced[mask, 1].mean()
        
        # Simple keyword extraction (most common words)
        keywords = extract_keywords(label_texts[:10])
        
        clusters.append({
            "cluster_id": f"cluster_{label}",
            "cluster_label": label,
            "centroid_lat": centroid_lat,
            "centroid_lng": centroid_lng,
            "size": mask.sum(),
            "keywords": keywords,
        })
    
    # Store cluster results
    with engine.begin() as conn:
        for c in clusters:
            conn.execute(
                sa.text("""
                    INSERT INTO cluster_results (cluster_id, cluster_label, centroid_lat, centroid_lng, size, keywords)
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
                }
            )
        
        # Update thread-cluster mappings
        for label in unique_labels:
            if label == -1:
                continue
            mask = cluster_labels == label
            for i in range(len(recent)):
                if mask[i]:
                    row = recent[i]
                    conn.execute(
                        sa.text("""
                            INSERT INTO thread_cluster_map (thread_id, cluster_id)
                            VALUES (:tid, :cid)
                            ON CONFLICT (thread_id, cluster_id) DO NOTHING
                        """),
                        {"tid": row[0], "cid": f"cluster_{label}"}
                    )
    
    return clusters

def extract_keywords(texts, n=5):
    """Simple keyword extraction using word frequency."""
    import re
    from collections import Counter
    
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "have", "will", "can", "could", "would", "should",
        "may", "might", "shall", "must", "and", "or", "not", "but", "if", "then",
        "else", "when", "where", "why", "how", "what", "which", "who", "whom",
        "this", "that", "these", "those", "it", "its", "there", "here", "now",
        "then", "so", "such", "with", "without", "for", "from", "in", "on", "at",
        "to", "of", "about", "between", "through", "during", "before", "after",
        "north", "south", "east", "west", "delhi", "city", "govt", "government",
        "people", "people", "many", "much", "some", "any", "one", "each", "every",
        "both", "few", "more", "most", "other", "same", "than", "too", "very",
        "just", "also", "only", "own", "too", "over", "under",
    }
    
    words = []
    for text in texts:
        cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower())
        words.extend([w for w in cleaned.split() if w not in stop_words and len(w) > 2])
    
    counter = Counter(words)
    return " ".join([word for word, count in counter.most_common(n)])

# --- Main ---
def main():
    log.info("="*50)
    log.info("Starting Conflux Worker...")
    log.info("="*50)
    
    # Step 1: Fetch new threads
    threads = fetch_new_threads()
    if not threads:
        log.info("No new threads to process.")
        return
    
    # Step 2: Insert into DB
    insert_batches(threads)
    
    # Step 3: Cluster
    clusters = cluster_threads()
    if clusters:
        log.info(f"Found {len(clusters)} clusters.")
        for c in clusters:
            log.info(f"  Cluster {c['cluster_label']} -> {c['size']} threads, keywords: {c['keywords']}")
    
    # Step 4: Optional: Run LLM proposals for each cluster
    # run_llm_proposals(clusters)
    
    log.info("Worker completed successfully.")

if __name__ == "__main__":
    main()
