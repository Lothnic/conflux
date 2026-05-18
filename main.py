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
