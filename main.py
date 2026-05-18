"""
Conflux Backend — Civic-tech AI Platform
Author: Lothnic
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional

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
    cluster_id: int
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


# ─── Endpoints ───────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "conflux"}


@app.post("/ingest")
async def ingest_complaints(data: ComplainList):
    """Ingest a batch of multilingual citizen complaints."""
    # TODO: Pass complaints to embedding/alignment pipeline
    return {"status": "ok", "ingested": len(data.complaints)}


@app.get("/ingest/reddit/delhi")
async def ingest_reddit_delhi(limit: int = 50):
    """Ingest hot threads from r/delhi (or mock data if no API key)."""
    import os
    from pathlib import Path
    from dotenv import load_dotenv
    
    load_dotenv()
    
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    
    if client_id and client_secret:
        # Use real Reddit API
        from src.ingestor.reddit import get_reddit_instance, fetch_hot_threads
        reddit = get_reddit_instance()
        threads = fetch_hot_threads(reddit, "delhi", limit)
        source = "reddit_api"
    else:
        # Use mock data
        mock_path = Path("data/reddit_hot_threads_mock.json")
        if mock_path.exists():
            import json
            with open(mock_path) as f:
                threads = json.load(f)
            source = "mock_data"
        else:
            return {"error": "No Reddit API key and no mock data available"}
    
    # Save to persistent storage
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
        }
    }


@app.post("/cluster")
async def cluster_complaints():
    """Run clustering on ingested complaints."""
    # TODO: Load ingested complaints, run sentence-transformers + UMAP + HDBSCAN
    return {"status": "ok", "message": "Clustering complete — proposals generated"}


@app.get("/proposals")
async def get_proposals():
    """Return generated infrastructure proposals."""
    proposals = []  # TODO: load from DB/JSON cache
    return {"proposals": proposals}


# ─── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
