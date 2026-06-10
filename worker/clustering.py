"""
Clustering pipeline for civic complaints.

Embeds text with sentence-transformers, combines with geo features,
runs HDBSCAN, and stores results in the database.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from pathlib import Path

import hdbscan
import numpy as np
import sqlalchemy as sa
import umap
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

import db

load_dotenv()

log = logging.getLogger("conflux.clustering")

# ─── Config ─────────────────────────────────────────────────────

HOURS_BACK = int(os.getenv("HOURS_BACK", "24"))
DEMO_MODE = os.getenv("CONFLUX_DEMO", "0") == "1"

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
EMBEDDING_DIM = 384

UMAP_N_COMPONENTS = int(os.getenv("UMAP_N_COMPONENTS", "2"))
UMAP_N_NEIGHBORS = int(os.getenv("UMAP_N_NEIGHBORS", "15"))
UMAP_MIN_DIST = float(os.getenv("UMAP_MIN_DIST", "0.1"))

HDBSCAN_MIN_CLUSTER_SIZE = int(os.getenv("HDBSCAN_MIN_CLUSTER_SIZE", "2"))
HDBSCAN_MIN_SAMPLES = int(os.getenv("HDBSCAN_MIN_SAMPLES", "1"))

TEXT_WEIGHT = float(os.getenv("TEXT_WEIGHT", "1.0"))
GEO_WEIGHT = float(os.getenv("GEO_WEIGHT", "0.3"))

BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL_DATA_DIR = BASE_DIR / "data"
LOCAL_CLUSTERS_FILE = LOCAL_DATA_DIR / "local_clusters.json"
LOCAL_THREADS_FILE = LOCAL_DATA_DIR / "local_threads_geojson.json"
LOCAL_THREADS_SOURCE_FILE = LOCAL_DATA_DIR / "local_threads.json"

SUBREDDIT = os.getenv("SUBREDDIT", "delhi")


# ─── Keywords ───────────────────────────────────────────────────

def extract_keywords(texts: list[str], n: int = 5) -> str:
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
    words: list[str] = []
    for text in texts:
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", text.lower())
        words.extend(w for w in cleaned.split() if w not in stop_words and len(w) > 2)
    counter = Counter(words)
    return " ".join(word for word, _ in counter.most_common(n))


# ─── Demo artifacts ─────────────────────────────────────────────

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

    clusters: list[dict] = []
    for label, (issue_type, members) in enumerate(grouped):
        if not members:
            continue
        centroid_lat = float(np.mean([m["lat"] for m in members]))
        centroid_lng = float(np.mean([m["lng"] for m in members]))
        keywords = extract_keywords([f"{m['title']} {m.get('content', '')}" for m in members], n=5)
        clusters.append({
            "cluster_id": f"demo-cluster-{label}",
            "cluster_label": label,
            "centroid_lat": centroid_lat,
            "centroid_lng": centroid_lng,
            "size": len(members),
            "keywords": keywords or issue_type.lower(),
        })
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


# ─── DB insertion ───────────────────────────────────────────────

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
                        ON CONFLICT (thread_id) DO UPDATE SET
                            coordinates = COALESCE(daily_ingest.coordinates, EXCLUDED.coordinates),
                            url = COALESCE(NULLIF(daily_ingest.url, ''), EXCLUDED.url)
                    """),
                    {"tid": t["thread_id"], "sub": t["subreddit"], "title": t["title"],
                     "content": t["content"], "flair": t["flair"], "upv": t["upvotes"],
                     "coords": json.dumps({
                         "lat": float(t["lat"]),
                         "lng": float(t["lng"]),
                         "location_text": t.get("location_text", ""),
                         "location_method": t.get("location_method", ""),
                         "location_confidence": t.get("location_confidence"),
                         "location_precision_meters": t.get("location_precision_meters"),
                     }) if t.get("lat") is not None else None,
                     "url": t.get("url", ""),
                     "pub": t["published_at"].isoformat() if hasattr(t["published_at"], "isoformat") else t["published_at"]},
                )

        with db.engine.begin() as conn:
            for t in batch:
                if t.get("lat") is not None and t.get("lng") is not None:
                    conn.execute(
                        sa.text("""
                            INSERT INTO thread_geo
                            (thread_id, lat, lng, source, location_text, location_method,
                             location_confidence, location_precision_meters, geocoder_provider,
                             geocoder_query, geocoder_raw)
                            VALUES (:tid, :lat, :lng, :src, :loctext, :method, :conf,
                                    :precision, :provider, :query, :raw)
                            ON CONFLICT (thread_id) DO UPDATE SET
                                lat = EXCLUDED.lat,
                                lng = EXCLUDED.lng,
                                source = EXCLUDED.source,
                                location_text = EXCLUDED.location_text,
                                location_method = EXCLUDED.location_method,
                                location_confidence = EXCLUDED.location_confidence,
                                location_precision_meters = EXCLUDED.location_precision_meters,
                                geocoder_provider = EXCLUDED.geocoder_provider,
                                geocoder_query = EXCLUDED.geocoder_query,
                                geocoder_raw = EXCLUDED.geocoder_raw
                        """),
                        {
                            "tid": t["thread_id"], "lat": float(t["lat"]),
                            "lng": float(t["lng"]), "src": t.get("source", "reddit"),
                            "loctext": t.get("location_text", ""),
                            "method": t.get("location_method", "unknown"),
                            "conf": t.get("location_confidence"),
                            "precision": t.get("location_precision_meters"),
                            "provider": t.get("geocoder_provider", ""),
                            "query": t.get("geocoder_query", ""),
                            "raw": t.get("geocoder_raw", ""),
                        },
                    )
        total_inserted += len(batch)
    log.info(f"Inserted {len(threads)} threads into daily_ingest.")
    return total_inserted


# ─── Clustering ─────────────────────────────────────────────────

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
    clusters: list[dict] = []
    for label in unique_labels:
        if label == -1:
            continue
        mask = cluster_labels == label
        mask_indices = np.where(mask)[0]
        member_texts = [texts[i] for i in mask_indices]
        keywords = extract_keywords(member_texts[:20])

        coords: list[tuple[float, float]] = []
        confidences: list[float] = []
        precisions: list[int] = []
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
                    conf = coord.get("location_confidence")
                    precision = coord.get("location_precision_meters")
                    if conf is not None:
                        confidences.append(float(conf))
                    if precision is not None:
                        precisions.append(int(precision))

        if coords:
            centroid_lat = float(np.mean([pair[0] for pair in coords]))
            centroid_lng = float(np.mean([pair[1] for pair in coords]))
            location_confidence = float(np.mean(confidences)) if confidences else None
            location_precision_meters = int(np.mean(precisions)) if precisions else None
        else:
            centroid_lat = None
            centroid_lng = None
            location_confidence = 0.0
            location_precision_meters = None

        clusters.append({
            "cluster_id": f"cluster_{label}",
            "cluster_label": label,
            "centroid_lat": float(centroid_lat) if centroid_lat is not None else None,
            "centroid_lng": float(centroid_lng) if centroid_lng is not None else None,
            "size": int(mask.sum()),
            "member_indices": mask_indices.tolist(),
            "keywords": keywords,
            "location_confidence": location_confidence,
            "location_precision_meters": location_precision_meters,
        })

    log.info("Running UMAP for visualization (2D projection only)...")
    umap_reducer = umap.UMAP(n_components=UMAP_N_COMPONENTS, n_neighbors=UMAP_N_NEIGHBORS, min_dist=UMAP_MIN_DIST, random_state=42)
    umap_reducer.fit_transform(combined)

    cluster_count = 0
    mapping_count = 0
    with db.engine.begin() as conn:
        for c in clusters:
            conn.execute(
                sa.text("""
                    INSERT INTO cluster_results
                    (cluster_id, cluster_label, centroid_lat, centroid_lng, size, keywords,
                     location_confidence, location_precision_meters)
                    VALUES (:cid, :clab, :clat, :clng, :sz, :kw, :conf, :precision)
                    ON CONFLICT (cluster_id) DO UPDATE SET
                        cluster_label = EXCLUDED.cluster_label,
                        centroid_lat = EXCLUDED.centroid_lat,
                        centroid_lng = EXCLUDED.centroid_lng,
                        size = EXCLUDED.size,
                        keywords = EXCLUDED.keywords,
                        location_confidence = EXCLUDED.location_confidence,
                        location_precision_meters = EXCLUDED.location_precision_meters
                """),
                {"cid": c["cluster_id"], "clab": c["cluster_label"], "clat": c["centroid_lat"],
                 "clng": c["centroid_lng"], "sz": c["size"], "kw": c["keywords"],
                 "conf": c.get("location_confidence"), "precision": c.get("location_precision_meters")},
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


# ─── Validation ─────────────────────────────────────────────────

def validate_results() -> None:
    log.info("Validating pipeline results...")
    with db.engine.connect() as conn:
        total_threads = conn.execute(sa.text("SELECT COUNT(*) FROM daily_ingest")).scalar()
        total_clusters = conn.execute(sa.text("SELECT COUNT(*) FROM cluster_results")).scalar()
        total_mappings = conn.execute(sa.text("SELECT COUNT(*) FROM thread_cluster_map")).scalar()
    log.info(f"Post-validation: {total_threads} threads, {total_clusters} clusters, {total_mappings} mappings.")
    if total_clusters == 0:
        log.warning("No clusters found! Check HDBSCAN parameters or filter your data.")
    log.info("Validation complete.")
