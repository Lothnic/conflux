"""
Conflux Backend — Civic-tech AI Platform
Author: Lothnic
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import os
import json
from uuid import uuid4
import sqlalchemy as sa

app = FastAPI(
    title="Conflux API",
    description="Civic-tech AI platform transforming citizen complaints into structured urban intelligence.",
    version="0.1.0",
)


# ─── Models ──────────────────────────────────────────────────────

class Complaint(BaseModel):
    text: str
    language: str
    lat: float
    lon: float
    source: str  # e.g., "reddit", "nextdoor", "govt_poll"


class ClusterProposal(BaseModel):
    cluster_id: str
    issue_type: str
    urgency: str  # "low", "medium", "high"
    location: dict  # lat, lon bounds
    summary: str
    recommendations: List[str]
    funding_sources: List[str]
    estimated_budget: str


class ComplainList(BaseModel):
    complaints: List[Complaint]


class ProposalResponse(BaseModel):
    proposals: List[ClusterProposal]


# ─── Database / Storage ──────────────────────────────────────────

DB_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/conflux")
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

CREATE TABLE IF NOT EXISTS thread_geo (
    thread_id    VARCHAR(32) PRIMARY KEY,
    lat          FLOAT,
    lng          FLOAT,
    source       VARCHAR,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS thread_cluster_map (
    thread_id     VARCHAR REFERENCES daily_ingest(thread_id),
    cluster_id    VARCHAR REFERENCES cluster_results(cluster_id),
    PRIMARY KEY (thread_id, cluster_id)
);
"""


def create_tables():
    with engine.begin() as conn:
        for stmt in CREATE_TABLES_SQL.strip().split(';'):
            if stmt.strip():
                conn.execute(sa.text(stmt))


def fetch_latest_clusters(limit: int = 50):
    with engine.connect() as conn:
        rows = conn.execute(sa.text("""
            SELECT cluster_id, cluster_label, centroid_lat, centroid_lng, size, keywords, created_at
            FROM cluster_results
            ORDER BY created_at DESC
            LIMIT :lim
        """), {"lim": limit}).fetchall()
    return [
        {
            "cluster_id": r[0],
            "cluster_label": r[1],
            "centroid_lat": r[2],
            "centroid_lng": r[3],
            "size": r[4],
            "keywords": r[5],
            "created_at": r[6].isoformat() if r[6] else None,
        }
        for r in rows
    ]


# ─── Proposal Heuristics ─────────────────────────────────────────

def infer_issue_type(keywords: str) -> str:
    text = (keywords or "").lower()
    if any(k in text for k in ["pothole", "road", "traffic", "lane", "signal"]):
        return "Road & Traffic"
    if any(k in text for k in ["garbage", "trash", "waste", "dump", "litter"]):
        return "Sanitation"
    if any(k in text for k in ["water", "drain", "sewer", "flood", "pipeline"]):
        return "Water & Drainage"
    if any(k in text for k in ["light", "lighting", "streetlight", "dark"]):
        return "Public Lighting"
    if any(k in text for k in ["park", "tree", "green", "noise", "pollution"]):
        return "Public Space & Environment"
    return "General Infrastructure"


def infer_urgency(size: int) -> str:
    if size >= 20:
        return "high"
    if size >= 8:
        return "medium"
    return "low"


def infer_budget(size: int) -> str:
    if size >= 20:
        return "$250k–$1M"
    if size >= 8:
        return "$50k–$250k"
    return "$10k–$50k"


def proposal_recommendations(issue_type: str) -> List[str]:
    if issue_type == "Road & Traffic":
        return [
            "Survey and prioritize repairs based on severity",
            "Repaint lane markings and improve signage",
            "Coordinate with traffic police for enforcement",
        ]
    if issue_type == "Sanitation":
        return [
            "Increase waste pickup frequency",
            "Add community bins and signage",
            "Launch local awareness and reporting campaign",
        ]
    if issue_type == "Water & Drainage":
        return [
            "Inspect and clear clogged drains",
            "Repair damaged pipelines",
            "Implement flood-mitigation micro-projects",
        ]
    if issue_type == "Public Lighting":
        return [
            "Audit non-functional streetlights",
            "Replace bulbs and wiring",
            "Pilot smart lighting in hotspots",
        ]
    if issue_type == "Public Space & Environment":
        return [
            "Create maintenance schedule for parks",
            "Install noise/pollution monitoring where needed",
            "Add greenery and buffer zones",
        ]
    return [
        "Conduct on-site inspection",
        "Engage local stakeholders",
        "Create phased repair plan",
    ]


# ─── Endpoints ───────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "conflux"}


@app.post("/ingest")
async def ingest_complaints(data: ComplainList):
    """Ingest a batch of multilingual citizen complaints."""
    create_tables()
    inserted = 0
    with engine.begin() as conn:
        for c in data.complaints:
            thread_id = uuid4().hex[:32]
            coords = json.dumps({"lat": float(c.lat), "lng": float(c.lon)})
            conn.execute(
                sa.text("""
                    INSERT INTO daily_ingest
                    (thread_id, subreddit, title, content, flair, upvotes, coordinates, published_at)
                    VALUES (:tid, :sub, :title, :content, :flair, :upv, :coords, NOW())
                    ON CONFLICT (thread_id) DO NOTHING
                """),
                {
                    "tid": thread_id,
                    "sub": c.source or "manual",
                    "title": "",
                    "content": c.text,
                    "flair": c.language,
                    "upv": 0,
                    "coords": coords,
                },
            )
            conn.execute(
                sa.text("""
                    INSERT INTO thread_geo (thread_id, lat, lng, source)
                    VALUES (:tid, :lat, :lng, :src)
                    ON CONFLICT (thread_id) DO NOTHING
                """),
                {
                    "tid": thread_id,
                    "lat": float(c.lat),
                    "lng": float(c.lon),
                    "src": c.source or "manual",
                },
            )
            inserted += 1
    return {"status": "ok", "ingested": inserted}


@app.get("/ingest/reddit/delhi")
async def ingest_reddit_delhi(limit: int = 50):
    """Ingest hot threads from r/delhi (or mock data if no API key)."""
    from pathlib import Path
    from dotenv import load_dotenv

    load_dotenv()

    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")

    if client_id and client_secret:
        from src.ingestor.reddit import get_reddit_instance, fetch_hot_threads
        reddit = get_reddit_instance()
        threads = fetch_hot_threads(reddit, "delhi", limit)
        source = "reddit_api"
    else:
        mock_path = Path("data/reddit_hot_threads_mock.json")
        if mock_path.exists():
            import json
            with open(mock_path) as f:
                threads = json.load(f)
            source = "mock_data"
        else:
            return {"error": "No Reddit API key and no mock data available"}

    data_dir = Path("data/threads")
    data_dir.mkdir(exist_ok=True)
    storage_file = data_dir / "r_delhi_threads.json"
    import json
    with open(storage_file, "w") as f:
        json.dump({"source": source, "count": len(threads), "threads": threads}, f, indent=2)

    return {
        "status": "ok",
        "source": source,
        "count": len(threads),
        "flair_breakdown": {
            t["flair"]: sum(1 for x in threads if x["flair"] == t["flair"])
            for t in [{"flair": t["flair"]} for t in threads[:5]]
        },
    }


@app.post("/cluster")
async def cluster_complaints():
    """Run clustering on ingested complaints."""
    # TODO: Load ingested complaints, run sentence-transformers + UMAP + HDBSCAN
    return {"status": "ok", "message": "Clustering complete — proposals generated"}


@app.get("/clusters")
async def get_clusters(limit: int = 50):
    """Return latest cluster summaries from the DB."""
    create_tables()
    try:
        clusters = fetch_latest_clusters(limit)
        return {"clusters": clusters}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/clusters/geojson")
async def get_clusters_geojson(limit: int = 200):
    """Return cluster centroids as GeoJSON FeatureCollection."""
    create_tables()
    try:
        clusters = fetch_latest_clusters(limit)
        features = []
        for c in clusters:
            lat = c.get("centroid_lat")
            lng = c.get("centroid_lng")
            if lat is None or lng is None:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lng, lat]},
                    "properties": {
                        "cluster_id": c.get("cluster_id"),
                        "size": c.get("size"),
                        "keywords": c.get("keywords"),
                        "created_at": c.get("created_at"),
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/threads/geojson")
async def get_threads_geojson(limit: int = 200):
    """Return ingested thread coordinates as GeoJSON FeatureCollection."""
    create_tables()
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text("""
                    SELECT thread_id, lat, lng, source, created_at
                    FROM thread_geo
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"lim": limit},
            ).fetchall()
        features = []
        for r in rows:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [r[2], r[1]]},
                    "properties": {
                        "thread_id": r[0],
                        "source": r[3],
                        "created_at": r[4].isoformat() if r[4] else None,
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/proposals")
async def get_proposals(limit: int = 50):
    """Return generated infrastructure proposals (heuristic baseline)."""
    create_tables()
    try:
        clusters = fetch_latest_clusters(limit)
        proposals = []
        for c in clusters:
            issue_type = infer_issue_type(c["keywords"])
            urgency = infer_urgency(c["size"])
            proposal = {
                "cluster_id": c["cluster_id"],
                "issue_type": issue_type,
                "urgency": urgency,
                "location": {
                    "centroid_lat": c["centroid_lat"],
                    "centroid_lng": c["centroid_lng"],
                },
                "summary": f"{issue_type} issues clustered from citizen complaints (size: {c['size']}).",
                "recommendations": proposal_recommendations(issue_type),
                "funding_sources": [
                    "Municipal budget",
                    "State infrastructure grants",
                    "Public-private partnerships",
                ],
                "estimated_budget": infer_budget(c["size"]),
            }
            proposals.append(proposal)
        return {"proposals": proposals}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
