"""
GitHub Actions Worker: Daily ingestion and clustering for Conflux.

This script:
1. Fetches new threads from r/delhi using Reddit's public JSON API (no auth required)
2. Runs combined text+geo clustering (embeddings + lat/lng features) with UMAP visualization
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import quote_plus
import numpy as np
import sqlalchemy as sa
from umap import UMAP
import hdbscan
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

# Add parent dir to path for shared db module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db

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
HOURS_BACK = int(os.getenv("HOURS_BACK", "24"))
RATE_LIMIT_DELAY = float(os.getenv("RATE_LIMIT_DELAY", "60.0"))  # Public API limit ~1 req/min

# Geocoding (Nominatim)
GEOCODE_ENABLED = os.getenv("GEOCODE_ENABLED", "1") == "1"
GEOCODE_CITY = os.getenv("GEOCODE_CITY", "Delhi")
GEOCODE_RATE_LIMIT = float(os.getenv("GEOCODE_RATE_LIMIT", "1.2"))  # seconds between requests
GEOCODE_USER_AGENT = os.getenv("GEOCODE_USER_AGENT", "conflux/0.1")

# Reddit public API
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "conflux/0.1")

# Embedding
MODEL_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
EMBEDDING_DIM = 384  # multilingual-MiniLM-L12-v2

DEMO_MODE = os.getenv("CONFLUX_DEMO", "0") == "1"

INFRA_KEYWORDS = [
    "pothole", "potholes", "waterlogging", "water logging",
    "garbage", "trash", "waste management", "sewer", "sewage",
    "drainage", "water supply", "drinking water",
    "streetlight", "street light", "broken signal", "traffic signal",
    "manhole", "open drain", "overflowing drain",
    "power cut", "power outage", "electricity outage",
    "road repair", "road damaged", "broken road", "bad road",
    "traffic jam", "traffic congestion",
    "illegal parking", "encroachment", "dust pollution",
    "air pollution", "noise pollution", "water contamination",
    "pipeline burst", "pipeline leak", "water crisis",
    "landfill", "ghazipur", "bhalswa", "okhla",
    "yamuna", "polluted", "contaminated",
    "सीवर", "पानी", "गंदगी", "कचरा", "टूटी", "सड़क",
    "गड्ढा", "जलभराव", "बिजली", "नाली",
]
UMAP_N_COMPONENTS = int(os.getenv("UMAP_N_COMPONENTS", "2"))
UMAP_N_NEIGHBORS = int(os.getenv("UMAP_N_NEIGHBORS", "15"))
UMAP_MIN_DIST = float(os.getenv("UMAP_MIN_DIST", "0.1"))

# HDBSCAN
HDBSCAN_MIN_CLUSTER_SIZE = int(os.getenv("HDBSCAN_MIN_CLUSTER_SIZE", "2"))
HDBSCAN_MIN_SAMPLES = int(os.getenv("HDBSCAN_MIN_SAMPLES", "1"))

# Combined text + geo clustering
TEXT_WEIGHT = float(os.getenv("TEXT_WEIGHT", "1.0"))
GEO_WEIGHT = float(os.getenv("GEO_WEIGHT", "0.3"))

# ---- DB Setup ----
BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL_DATA_DIR = BASE_DIR / "data"
LOCAL_CLUSTERS_FILE = LOCAL_DATA_DIR / "local_clusters.json"
LOCAL_THREADS_FILE = LOCAL_DATA_DIR / "local_threads_geojson.json"
LOCAL_THREADS_SOURCE_FILE = LOCAL_DATA_DIR / "local_threads.json"


def build_demo_threads() -> list[dict]:
    now = datetime.now(timezone.utc)
    demo = [
        {
            "thread_id": "demo-road-1",
            "subreddit": SUBREDDIT,
            "title": "Potholes on Ring Road near AIIMS are getting worse",
            "content": "Multiple lanes have deep potholes and traffic is crawling every evening.",
            "flair": "Roads",
            "upvotes": 125,
            "published_at": now,
            "lat": 28.5665,
            "lng": 77.2100,
        },
        {
            "thread_id": "demo-road-2",
            "subreddit": SUBREDDIT,
            "title": "Traffic light at Lajpat Nagar intersection is broken",
            "content": "Cars are blocking the crossing and pedestrians cannot safely cross.",
            "flair": "Traffic",
            "upvotes": 88,
            "published_at": now,
            "lat": 28.5678,
            "lng": 77.2432,
        },
        {
            "thread_id": "demo-road-3",
            "subreddit": SUBREDDIT,
            "title": "Road repair needed near Connaught Place outer circle",
            "content": "The surface is uneven and two wheelers are swerving around damaged patches.",
            "flair": "Roads",
            "upvotes": 97,
            "published_at": now,
            "lat": 28.6315,
            "lng": 77.2167,
        },
        {
            "thread_id": "demo-sanitation-1",
            "subreddit": SUBREDDIT,
            "title": "Garbage overflow near Karol Bagh market",
            "content": "Bins are full and the street smells bad after noon.",
            "flair": "Sanitation",
            "upvotes": 142,
            "published_at": now,
            "lat": 28.6519,
            "lng": 77.1909,
        },
        {
            "thread_id": "demo-sanitation-2",
            "subreddit": SUBREDDIT,
            "title": "Trash collection missed again in Dwarka sector 10",
            "content": "Residents report bags piling up for the third day.",
            "flair": "Waste",
            "upvotes": 76,
            "published_at": now,
            "lat": 28.5873,
            "lng": 77.0444,
        },
        {
            "thread_id": "demo-sanitation-3",
            "subreddit": SUBREDDIT,
            "title": "Illegal dumping behind the park in Janakpuri",
            "content": "Construction debris and waste are blocking the back lane.",
            "flair": "Waste",
            "upvotes": 64,
            "published_at": now,
            "lat": 28.6216,
            "lng": 77.0910,
        },
        {
            "thread_id": "demo-water-1",
            "subreddit": SUBREDDIT,
            "title": "Severe waterlogging after rain in East Delhi",
            "content": "Drainage is clogged and the road stays flooded for hours.",
            "flair": "Drainage",
            "upvotes": 133,
            "published_at": now,
            "lat": 28.6510,
            "lng": 77.3027,
        },
        {
            "thread_id": "demo-water-2",
            "subreddit": SUBREDDIT,
            "title": "Sewer smell and drain overflow near Shahdara",
            "content": "Residents say the drain has not been cleaned in weeks.",
            "flair": "Drainage",
            "upvotes": 91,
            "published_at": now,
            "lat": 28.6776,
            "lng": 77.2910,
        },
        {
            "thread_id": "demo-water-3",
            "subreddit": SUBREDDIT,
            "title": "Water pipeline leak causing road damage in Saket",
            "content": "The broken pipe has created puddles and a slippery road surface.",
            "flair": "Water",
            "upvotes": 58,
            "published_at": now,
            "lat": 28.5245,
            "lng": 77.2066,
        },
    ]
    return demo


def build_demo_clusters(threads: list[dict]) -> list[dict]:
    buckets = [
        ("Road & Traffic", ["road", "pothole", "traffic", "signal", "lane"]),
        ("Sanitation", ["garbage", "trash", "waste", "dump", "bins", "litter"]),
        ("Water & Drainage", ["water", "drain", "sewer", "flood", "pipeline", "leak", "waterlogging"]),
    ]
    grouped: list[tuple[str, list[dict]]] = [(name, []) for name, _ in buckets]

    for thread in threads:
        blob = f"{thread['title']} {thread.get('content', '')}".lower()
        for idx, (_, keywords) in enumerate(buckets):
            if any(keyword in blob for keyword in keywords):
                grouped[idx][1].append(thread)
                break
        else:
            grouped[0][1].append(thread)

    clusters = []
    for label, (issue_type, members) in enumerate(grouped):
        if not members:
            continue
        centroid_lat = float(np.mean([m["lat"] for m in members]))
        centroid_lng = float(np.mean([m["lng"] for m in members]))
        keywords = extract_keywords([f"{m['title']} {m.get('content', '')}" for m in members], n=5)
        clusters.append(
            {
                "cluster_id": f"demo-cluster-{label}",
                "cluster_label": label,
                "centroid_lat": centroid_lat,
                "centroid_lng": centroid_lng,
                "size": len(members),
                "keywords": keywords or issue_type.lower(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return clusters


def write_local_artifacts(threads: list[dict], clusters: list[dict]) -> None:
    LOCAL_DATA_DIR.mkdir(exist_ok=True)
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [thread["lng"], thread["lat"]]},
            "properties": {
                "thread_id": thread["thread_id"],
                "source": thread.get("subreddit", SUBREDDIT),
                "created_at": thread["published_at"].isoformat() if hasattr(thread["published_at"], "isoformat") else thread["published_at"],
            },
        }
        for thread in threads
    ]

    with open(LOCAL_THREADS_SOURCE_FILE, "w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    **thread,
                    "published_at": thread["published_at"].isoformat() if hasattr(thread["published_at"], "isoformat") else thread["published_at"],
                }
                for thread in threads
            ],
            f,
            indent=2,
            ensure_ascii=False,
        )

    with open(LOCAL_CLUSTERS_FILE, "w", encoding="utf-8") as f:
        json.dump(clusters, f, indent=2, ensure_ascii=False)

    with open(LOCAL_THREADS_FILE, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, indent=2, ensure_ascii=False)


# ====================================================
# STEP 1: Multi-Source Reddit Fetch
# ====================================================

# Subreddits to scan for Delhi NCR infrastructure complaints
TARGET_SUBS = os.getenv("TARGET_SUBS", "delhi,india,NewDelhi").split(",")

# Infrastructure search queries for Reddit search API
SEARCH_QUERIES = [
    "pothole OR waterlogging OR drainage OR sewer OR garbage",
    "broken road OR traffic jam OR power cut OR streetlight",
    "water supply OR pollution OR dust OR footpath OR parking",
    "metro OR bus stop OR sanitation OR waste OR pipeline",
]


def _fetch_reddit_url(url: str) -> dict | None:
    """Fetch JSON from a Reddit endpoint with rate limiting."""
    time.sleep(1.2)
    try:
        req = Request(url, method="GET")
        req.add_header("User-Agent", "conflux/0.1 (anonymous)")
        resp = urlopen(req, timeout=15)
        return json.loads(resp.read().decode())
    except (HTTPError, URLError, json.JSONDecodeError) as e:
        log.warning(f"Reddit fetch failed for {url[:80]}: {e}")
        return None


def fetch_new_threads() -> list[dict]:
    """Fetch infra-relevant threads from multiple Delhi NCR subreddits."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
    all_threads: dict[str, dict] = {}
    seen_ids = set()

    for sub in TARGET_SUBS:
        sub = sub.strip()

        # Fetch new posts
        new_url = f"https://old.reddit.com/r/{sub}/new.json?limit=50"
        log.info(f"Fetching r/{sub}/new...")
        data = _fetch_reddit_url(new_url)
        if data:
            for post_data in data.get("data", {}).get("children", []):
                post = post_data.get("data", {})
                created_utc = post.get("created_utc", 0)
                created_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                if created_dt < cutoff:
                    continue
                tid = post.get("id", "")
                if not tid or tid in seen_ids:
                    continue
                title = post.get("title", "")
                content = post.get("selftext", "")
                blob = f"{title} {content}".lower()
                if any(kw in blob for kw in INFRA_KEYWORDS):
                    seen_ids.add(tid)
                    all_threads[tid] = _make_thread(tid, post, sub)

        # Search posts by infra keywords
        for query in SEARCH_QUERIES:
            encoded = quote_plus(query)
            search_url = f"https://old.reddit.com/r/{sub}/search.json?q={encoded}&sort=new&restrict_sr=on&limit=15&t=month"
            log.info(f"Searching r/{sub} with: {query[:50]}...")
            data = _fetch_reddit_url(search_url)
            if not data:
                continue
            for post_data in data.get("data", {}).get("children", []):
                post = post_data.get("data", {})
                tid = post.get("id", "")
                if not tid or tid in seen_ids:
                    continue
                title = post.get("title", "")
                content = post.get("selftext", "")
                blob = f"{title} {content}".lower()
                if any(kw in blob for kw in INFRA_KEYWORDS):
                    seen_ids.add(tid)
                    all_threads[tid] = _make_thread(tid, post, sub)

    threads = list(all_threads.values())
    log.info(f"Multi-source fetch returned {len(threads)} infra-relevant threads from {TARGET_SUBS}.")
    return threads


def _make_thread(thread_id: str, post: dict, subreddit: str) -> dict:
    created_utc = post.get("created_utc", 0)
    created_dt = datetime.fromtimestamp(created_utc, tz=timezone.utc)
    title = post.get("title", "")
    content = post.get("selftext", "")
    lat, lng = resolve_coordinates(title, content)
    return {
        "thread_id": thread_id,
        "subreddit": subreddit,
        "title": title,
        "content": content,
        "flair": post.get("link_flair_text", "") or "",
        "upvotes": post.get("score", 0),
        "published_at": created_dt,
        "lat": lat,
        "lng": lng,
        "url": f"https://reddit.com/r/{subreddit}/comments/{thread_id}",
    }


def geocode_text(query: str) -> tuple[float | None, float | None]:
    if not GEOCODE_ENABLED:
        return None, None
    try:
        url = (
            "https://nominatim.openstreetmap.org/search?"
            f"format=json&q={quote_plus(query)}&limit=1"
        )
        req = Request(url, method="GET")
        req.add_header("User-Agent", GEOCODE_USER_AGENT)
        resp = urlopen(req, timeout=15)
        results = json.loads(resp.read().decode())
        if not results:
            return None, None
        lat = float(results[0].get("lat"))
        lng = float(results[0].get("lon"))
        return lat, lng
    except HTTPError as e:
        if e.code == 429:
            log.warning(f"Geocoding rate-limited, backing off 3s...")
            time.sleep(3)
        else:
            log.warning(f"Geocoding failed for '{query[:60]}...': {e}")
        return None, None
    except Exception as e:
        log.warning(f"Geocoding failed for '{query[:60]}...': {e}")
        return None, None


def resolve_coordinates(title: str, content: str) -> tuple[float | None, float | None]:
    if not GEOCODE_ENABLED:
        return None, None
    time.sleep(GEOCODE_RATE_LIMIT)
    query = f"{title} {content} {GEOCODE_CITY}".strip()
    lat, lng = geocode_text(query)
    if lat is None and lng is None:
        time.sleep(GEOCODE_RATE_LIMIT)
        lat, lng = geocode_text(GEOCODE_CITY)
    return lat, lng


# ====================================================
# STEP 2: Dedup + Bulk Insert
# ====================================================

def check_existing(thread_id: str) -> bool:
    with db.engine.connect() as conn:
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
        with db.engine.begin() as conn:
            for t in batch:
                conn.execute(
                    sa.text("""
                        INSERT INTO daily_ingest
                        (thread_id, subreddit, title, content, flair, upvotes, coordinates, url, published_at)
                        VALUES (:tid, :sub, :title, :content, :flair, :upv, :coords, :url, :pub)
                        ON CONFLICT (thread_id) DO NOTHING
                    """),
                    {"tid": t["thread_id"], "sub": t["subreddit"], "title": t["title"],
                     "content": t["content"], "flair": t["flair"], "upv": t["upvotes"],
                     "coords": json.dumps({"lat": float(t["lat"]), "lng": float(t["lng"])}) if t.get("lat") is not None else None,
                     "url": t.get("url", ""),
                     "pub": t["published_at"].isoformat() if hasattr(t["published_at"], "isoformat") else t["published_at"]},
                )

        with db.engine.begin() as conn:
            for t in batch:
                if t.get("lat") is not None and t.get("lng") is not None:
                    conn.execute(
                        sa.text("""
                            INSERT INTO thread_geo (thread_id, lat, lng, source)
                            VALUES (:tid, :lat, :lng, :src)
                            ON CONFLICT (thread_id) DO NOTHING
                        """),
                        {"tid": t["thread_id"], "lat": float(t["lat"]), "lng": float(t["lng"]), "src": "reddit"},
                    )
        total_inserted += len(batch)
    log.info(f"Inserted {len(threads)} threads into daily_ingest.")
    return total_inserted


# ====================================================
# STEP 3: Clustering (on FULL embedding space)
# ====================================================

def cluster_threads() -> list[dict]:
    with db.engine.connect() as conn:
        recent = conn.execute(
            sa.text("SELECT thread_id, title, content, coordinates FROM daily_ingest "
                    "ORDER BY published_at DESC "
                    "LIMIT :lim"),
            {"lim": 500},
        ).fetchall()

    if len(recent) < HDBSCAN_MIN_CLUSTER_SIZE:
        log.warning(f"Too few threads ({len(recent)}) found for clustering. Skipping.")
        return []

    log.info(f"Clustering {len(recent)} threads using combined text+geo space...")

    encoder = SentenceTransformer(MODEL_NAME)
    texts = [f"{row[1]} {row[2]}".strip() if row[2] else row[1] for row in recent]
    text_embeddings = encoder.encode(texts, show_progress_bar=True)
    text_embeddings = np.array(text_embeddings)
    log.info(f"Generated text embeddings: {text_embeddings.shape}")

    # Build geo features (lat, lng) with normalization
    geo_features = []
    for row in recent:
        coord = row[3]
        if isinstance(coord, str):
            try:
                coord = json.loads(coord)
            except json.JSONDecodeError:
                coord = None
        if isinstance(coord, dict):
            lat = coord.get("lat")
            lng = coord.get("lng")
        else:
            lat = None
            lng = None
        geo_features.append([lat, lng])

    geo_features = np.array(geo_features, dtype=float)
    has_geo = not np.isnan(geo_features).all()

    if has_geo:
        if np.isnan(geo_features).any():
            col_means = np.nanmean(geo_features, axis=0)
            inds = np.where(np.isnan(geo_features))
            geo_features[inds] = np.take(col_means, inds[1])
        geo_norm = (geo_features - geo_features.mean(axis=0)) / (geo_features.std(axis=0) + 1e-8)

    text_norm = (text_embeddings - text_embeddings.mean(axis=0)) / (text_embeddings.std(axis=0) + 1e-8)

    if has_geo:
        combined = np.concatenate(
            [TEXT_WEIGHT * text_norm, GEO_WEIGHT * geo_norm],
            axis=1,
        )
    else:
        combined = text_norm

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=HDBSCAN_MIN_CLUSTER_SIZE,
        min_samples=HDBSCAN_MIN_SAMPLES,
        metric="euclidean",
        cluster_selection_epsilon=0.5,
        algorithm="best",
    )
    cluster_labels = clusterer.fit_predict(combined)
    log.info(f"HDBSCAN found {len(set(cluster_labels) - {-1})} clusters, {sum(cluster_labels == -1)} noise points.")

    unique_labels = set(cluster_labels)
    clusters = []
    for label in unique_labels:
        if label == -1:
            continue
        mask = cluster_labels == label
        mask_indices = np.where(mask)[0]
        member_texts = [texts[i] for i in mask_indices]
        keywords = extract_keywords(member_texts[:20])

        coords = []
        for idx in mask_indices:
            coord = recent[idx][3]
            if isinstance(coord, str):
                try:
                    coord = json.loads(coord)
                except json.JSONDecodeError:
                    coord = None
            if isinstance(coord, dict):
                lat = coord.get("lat")
                lng = coord.get("lng")
                if lat is not None and lng is not None:
                    coords.append((lat, lng))

        if coords:
            centroid_lat = float(np.mean([pair[0] for pair in coords]))
            centroid_lng = float(np.mean([pair[1] for pair in coords]))
        else:
            seed = hash(f"cluster_{label}") % 1000 / 1000.0
            centroid_lat = 28.6139 + (seed - 0.5) * 0.1
            centroid_lng = 77.2090 + ((seed * 1.3) % 1.0 - 0.5) * 0.1

        clusters.append({
            "cluster_id": f"cluster_{label}",
            "cluster_label": label,
            "centroid_lat": float(centroid_lat) if centroid_lat is not None else None,
            "centroid_lng": float(centroid_lng) if centroid_lng is not None else None,
            "size": int(mask.sum()),
            "member_indices": mask_indices.tolist(),
            "keywords": keywords,
        })

    log.info("Running UMAP for visualization (2D projection only)...")
    umap_reducer = UMAP(n_components=UMAP_N_COMPONENTS, n_neighbors=UMAP_N_NEIGHBORS, min_dist=UMAP_MIN_DIST, random_state=42)
    umap_coords = umap_reducer.fit_transform(combined)

    cluster_count = 0
    mapping_count = 0
    with db.engine.begin() as conn:
        for c in clusters:
            conn.execute(
                sa.text("""
                    INSERT INTO cluster_results
                    (cluster_id, cluster_label, centroid_lat, centroid_lng, size, keywords)
                    VALUES (:cid, :clab, :clat, :clng, :sz, :kw)
                    ON CONFLICT (cluster_id) DO UPDATE SET
                        cluster_label = EXCLUDED.cluster_label,
                        centroid_lat = EXCLUDED.centroid_lat,
                        centroid_lng = EXCLUDED.centroid_lng,
                        size = EXCLUDED.size,
                        keywords = EXCLUDED.keywords
                """),
                {"cid": c["cluster_id"], "clab": c["cluster_label"], "clat": c["centroid_lat"],
                 "clng": c["centroid_lng"], "sz": c["size"], "kw": c["keywords"]},
            )
            cluster_count += 1
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
    with db.engine.connect() as conn:
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
        if DEMO_MODE or not db.database_available():
            log.warning("Database unavailable. Writing local demo artifacts instead.")
            threads = build_demo_threads()
            clusters = build_demo_clusters(threads)
            write_local_artifacts(threads, clusters)
            log.info(f"Wrote {len(threads)} demo threads and {len(clusters)} demo clusters.")
            log.info("Worker completed successfully in local demo mode.")
            return

        db.create_tables()
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

        log.info("--- Step 5: Proposal Generation ---")
        from proposals import generate_proposal_for_cluster, store_proposal
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
