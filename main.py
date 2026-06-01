"""
Conflux Backend — Civic-tech AI Platform
Author: Lothnic
"""
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import List, AsyncGenerator
import os
import json
import asyncio
from uuid import uuid4
from pathlib import Path
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
    communication_plan: List[str] = []
    responsible_agencies: List[str] = []
    impact_rationale: str = ""


class ComplainList(BaseModel):
    complaints: List[Complaint]


class ProposalResponse(BaseModel):
    proposals: List[ClusterProposal]


# ─── Database / Storage ──────────────────────────────────────────

import db

DEMO_MODE = os.getenv("CONFLUX_DEMO", "0") == "1"
BASE_DIR = Path(__file__).resolve().parent
LOCAL_DATA_DIR = BASE_DIR / "data"
LOCAL_CLUSTERS_FILE = LOCAL_DATA_DIR / "local_clusters.json"
LOCAL_THREADS_FILE = LOCAL_DATA_DIR / "local_threads_geojson.json"
LOCAL_THREADS_SOURCE_FILE = LOCAL_DATA_DIR / "local_threads.json"


def database_available() -> bool:
    if DEMO_MODE:
        return False
    return db.database_available()


def create_tables() -> bool:
    if not database_available():
        return False
    db.create_tables()
    return True


def fetch_latest_clusters(limit: int = 50):
    if DEMO_MODE and LOCAL_CLUSTERS_FILE.exists():
        with open(LOCAL_CLUSTERS_FILE, "r", encoding="utf-8") as f:
            clusters = json.load(f)
        if clusters:
            return clusters[:limit]

    if not database_available():
        return []

    with db.engine.connect() as conn:
        rows = conn.execute(sa.text("""
            SELECT cluster_id, cluster_label, centroid_lat, centroid_lng, size, keywords,
                   created_at, location_confidence, location_precision_meters
            FROM cluster_results
            WHERE (:include_demo = 1 OR cluster_id NOT LIKE 'demo-%')
            ORDER BY created_at DESC
            LIMIT :lim
        """), {"lim": limit, "include_demo": 1 if DEMO_MODE else 0}).fetchall()
    if rows:
        return [
            {
                "cluster_id": r[0],
                "cluster_label": r[1],
                "centroid_lat": r[2],
                "centroid_lng": r[3],
                "size": r[4],
                "keywords": r[5],
                "created_at": r[6] if r[6] else None,
                "location_confidence": r[7],
                "location_precision_meters": r[8],
            }
            for r in rows
        ]

    if DEMO_MODE and LOCAL_CLUSTERS_FILE.exists():
        with open(LOCAL_CLUSTERS_FILE, "r", encoding="utf-8") as f:
            clusters = json.load(f)
        return clusters[:limit]
    return []


def fetch_sources_for_cluster(cluster_id: str, limit: int = 8) -> list[dict]:
    """Fetch thread sources for a cluster from the DB."""
    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                sa.text("""
                    SELECT d.thread_id, d.subreddit, d.title, d.url
                    FROM daily_ingest d
                    JOIN thread_cluster_map tcm ON d.thread_id = tcm.thread_id
                    WHERE tcm.cluster_id = :cid
                    LIMIT :lim
                """),
                {"cid": cluster_id, "lim": limit},
            ).fetchall()
        return [
            {
                "id": r[0],
                "subreddit": r[1] or "delhi",
                "title": r[2],
                "url": source_url(r[0], r[1], r[3]),
            }
            for r in rows
        ]
    except Exception:
        return []


def source_url(thread_id: str, source: str | None, stored_url: str | None = None) -> str:
    if stored_url:
        return stored_url
    source = source or "delhi"
    if source.startswith("news:") or source.startswith("gov:"):
        return ""
    return f"https://reddit.com/r/{source}/comments/{thread_id}"


# ─── Proposal Heuristics ─────────────────────────────────────────

def fetch_latest_threads(limit: int = 50):
    if DEMO_MODE and LOCAL_THREADS_SOURCE_FILE.exists():
        with open(LOCAL_THREADS_SOURCE_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        threads = payload if isinstance(payload, list) else payload.get("threads", [])

        clusters = fetch_latest_clusters(50)
        cluster_by_issue = {}
        for c in clusters:
            issue = infer_issue_type(c["keywords"])
            if issue not in cluster_by_issue:
                cluster_by_issue[issue] = c["cluster_id"]

        return [
            {
                "id": t.get("id") or t.get("thread_id", ""),
                "title": t.get("title", ""),
                "url": source_url(t.get("id") or t.get("thread_id", ""), t.get("subreddit") or t.get("source") or "delhi", t.get("url", "")),
                "author": t.get("author", "system"),
                "created_utc": t.get("created_utc") or t.get("published_at"),
                "upvotes": int(t.get("upvotes") or 0),
                "num_comments": int(t.get("num_comments") or 0),
                "flair": t.get("flair", ""),
                "content": t.get("content", ""),
                "subreddit": t.get("subreddit") or t.get("source") or "delhi",
                "lat": t.get("lat"),
                "lng": t.get("lng"),
                "cluster_id": t.get("cluster_id") or cluster_by_issue.get(
                    infer_issue_type(f"{t.get('title', '')} {t.get('content', '')} {t.get('flair', '')}")
                ),
            }
            for t in threads[:limit]
        ]

    if not database_available():
        return []

    with db.engine.connect() as conn:
        rows = conn.execute(
            sa.text("""
                SELECT d.thread_id, d.subreddit, d.title, d.content, d.flair, d.upvotes, d.published_at,
                       tg.lat, tg.lng, tcm.cluster_id, d.url, tg.location_text, tg.location_method,
                       tg.location_confidence, tg.location_precision_meters
                FROM daily_ingest d
                LEFT JOIN thread_geo tg ON d.thread_id = tg.thread_id
                LEFT JOIN thread_cluster_map tcm ON d.thread_id = tcm.thread_id
                ORDER BY d.published_at DESC
                LIMIT :lim
            """),
            {"lim": limit},
        ).fetchall()

    return [
        {
            "id": row[0],
            "title": row[2] or "",
            "url": source_url(row[0], row[1], row[10]),
            "author": "system",
            "created_utc": row[6] if row[6] else None,
            "upvotes": int(row[5] or 0),
            "num_comments": 0,
            "flair": row[4] or "",
            "content": row[3] or "",
            "subreddit": row[1] or "delhi",
            "lat": row[7],
            "lng": row[8],
            "cluster_id": row[9],
            "location_text": row[11],
            "location_method": row[12],
            "location_confidence": row[13],
            "location_precision_meters": row[14],
        }
        for row in rows
    ]


# ─── Proposal Heuristics ─────────────────────────────────────────

def infer_issue_type(keywords: str) -> str:
    text = (keywords or "").lower()
    if any(k in text for k in ["light", "lighting", "streetlight", "dark"]):
        return "Public Lighting"
    if any(k in text for k in ["pothole", "road", "traffic", "lane", "signal"]):
        return "Road & Traffic"
    if any(k in text for k in ["garbage", "trash", "waste", "dump", "litter"]):
        return "Sanitation"
    if any(k in text for k in ["water", "drain", "sewer", "flood", "pipeline"]):
        return "Water & Drainage"
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
        return "₹2-8 crore"
    if size >= 8:
        return "₹40 lakh-₹2 crore"
    return "₹8-40 lakh"


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


# Delhi bodies that own each category of fix. Used as the no-LLM fallback so the
# UI never shows blank "Responsible Agencies".
_AGENCY_MAP = {
    "Road & Traffic": ["Public Works Department (PWD)", "Delhi Traffic Police", "Municipal Corporation of Delhi (MCD)"],
    "Sanitation": ["Municipal Corporation of Delhi (MCD)", "Department of Urban Development", "Swachh Bharat Mission (Urban)"],
    "Water & Drainage": ["Delhi Jal Board (DJB)", "Public Works Department (PWD)", "Irrigation & Flood Control Department"],
    "Public Lighting": ["Municipal Corporation of Delhi (MCD)", "BSES/Tata Power-DDL (DISCOMs)", "Public Works Department (PWD)"],
    "Public Space & Environment": ["Delhi Development Authority (DDA)", "Delhi Pollution Control Committee (DPCC)", "Forest Department, GNCTD"],
}


def responsible_agencies(issue_type: str) -> List[str]:
    return _AGENCY_MAP.get(issue_type, ["Municipal Corporation of Delhi (MCD)", "Office of the District Magistrate"])


def proposal_communication_plan(issue_type: str) -> List[str]:
    """Sequenced stakeholder-outreach steps (heuristic fallback)."""
    lead = responsible_agencies(issue_type)[0]
    return [
        f"Week 1: File a consolidated grievance with {lead} via the Delhi PGMS portal, citing the clustered citizen reports",
        "Week 1: Brief the local Resident Welfare Association (RWA) and ward councillor to build community backing",
        "Week 2: Submit a formal representation to the area MLA for MLA-LAD fund consideration",
        "Week 3: Issue a press note to local Delhi dailies to raise public visibility",
        "Week 4: Escalate to the LG / DDC office if no acknowledgement is received within the PGMS SLA",
    ]


def impact_rationale(issue_type: str, size: int) -> str:
    """One-line justification for the assigned urgency with a rough reach estimate."""
    affected = max(size, 1) * 75  # rough per-complaint catchment of affected residents
    level = infer_urgency(size)
    return (
        f"{level.capitalize()} urgency: {size} clustered complaints indicate a recurring {issue_type.lower()} "
        f"problem affecting an estimated {affected:,}+ residents in the surrounding area."
    )


# ─── Endpoints ───────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "conflux"}


@app.post("/ingest")
async def ingest_complaints(data: ComplainList):
    """Ingest a batch of multilingual citizen complaints."""
    if not create_tables():
        raise HTTPException(status_code=503, detail="Database is unavailable")

    inserted = 0
    with db.engine.begin() as conn:
        for c in data.complaints:
            thread_id = uuid4().hex[:32]
            coords = json.dumps({"lat": float(c.lat), "lng": float(c.lon)})
            conn.execute(
                sa.text("""
                    INSERT INTO daily_ingest
                    (thread_id, subreddit, title, content, flair, upvotes, coordinates, published_at)
                    VALUES (:tid, :sub, :title, :content, :flair, :upv, :coords, CURRENT_TIMESTAMP)
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


@app.post("/cluster")
async def cluster_complaints():
    """Run clustering on ingested complaints."""
    if not create_tables():
        raise HTTPException(status_code=503, detail="Database is unavailable")

    try:
        from worker.ingest_and_cluster import cluster_threads

        clusters = cluster_threads()
        return {
            "status": "ok",
            "message": "Clustering complete",
            "clusters": len(clusters),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/clusters")
async def get_clusters(limit: int = 50):
    """Return latest cluster summaries from the DB."""
    create_tables()

    try:
        clusters = fetch_latest_clusters(limit)
        return {"clusters": clusters}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/threads")
async def get_threads(limit: int = 50):
    """Return recent thread records for the sidebar."""
    create_tables()

    try:
        threads = fetch_latest_threads(limit)
        return {
            "threads": threads,
            "source": "local_demo" if DEMO_MODE else "database",
            "count": len(threads),
        }
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
                        "location_confidence": c.get("location_confidence"),
                        "location_precision_meters": c.get("location_precision_meters"),
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/threads/geojson")
async def get_threads_geojson(limit: int = 200):
    """Return ingested thread coordinates as GeoJSON FeatureCollection."""
    if DEMO_MODE and LOCAL_THREADS_FILE.exists():
        with open(LOCAL_THREADS_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
        features = payload.get("features", [])
        if features:
            payload["features"] = features[:limit]
            return payload

    create_tables()

    try:
        with db.engine.connect() as conn:
            rows = conn.execute(
                sa.text("""
                    SELECT tg.thread_id, tg.lat, tg.lng, tg.source, tg.created_at, tcm.cluster_id,
                           tg.location_text, tg.location_method, tg.location_confidence,
                           tg.location_precision_meters
                    FROM thread_geo tg
                    LEFT JOIN thread_cluster_map tcm ON tg.thread_id = tcm.thread_id
                    ORDER BY tg.created_at DESC
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
                        "created_at": r[4] if r[4] else None,
                        "cluster_id": r[5],
                        "location_text": r[6],
                        "location_method": r[7],
                        "location_confidence": r[8],
                        "location_precision_meters": r[9],
                    },
                }
            )
        return {"type": "FeatureCollection", "features": features}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/proposals")
async def get_proposals(limit: int = 50):
    """Return generated infrastructure proposals (LLM-powered with heuristic fallback)."""
    create_tables()

    try:
        from proposals import fetch_stored_proposals

        stored = fetch_stored_proposals(db.engine, limit)
        if not DEMO_MODE:
            stored = [p for p in stored if not str(p["cluster_id"]).startswith("demo-")]

        clusters = fetch_latest_clusters(limit)
        if not DEMO_MODE:
            clusters = [c for c in clusters if not str(c["cluster_id"]).startswith("demo-")]
        clusters_by_id = {c["cluster_id"]: c for c in clusters}
        proposals = []
        seen_cluster_ids = set()

        for p in stored:
            c = clusters_by_id.get(p["cluster_id"], {})
            sources = fetch_sources_for_cluster(p["cluster_id"])
            issue = p["issue_type"]
            seen_cluster_ids.add(p["cluster_id"])
            proposals.append({
                "cluster_id": p["cluster_id"],
                "issue_type": issue,
                "urgency": p["urgency"],
                "location": {
                    "lat": p.get("centroid_lat") if p.get("centroid_lat") is not None else c.get("centroid_lat"),
                    "lon": p.get("centroid_lng") if p.get("centroid_lng") is not None else c.get("centroid_lng"),
                    "confidence": p.get("location_confidence") if p.get("location_confidence") is not None else c.get("location_confidence"),
                    "precision_meters": p.get("location_precision_meters") if p.get("location_precision_meters") is not None else c.get("location_precision_meters"),
                    "method": "cluster_centroid",
                },
                "summary": p["summary"],
                "recommendations": p["recommendations"],
                "funding_sources": p["funding_sources"],
                "estimated_budget": p["estimated_budget"],
                "communication_plan": p.get("communication_plan") or proposal_communication_plan(issue),
                "responsible_agencies": p.get("responsible_agencies") or responsible_agencies(issue),
                "impact_rationale": p.get("impact_rationale")
                    or f"{p['urgency'].capitalize()} urgency based on the volume of clustered citizen complaints about this {issue.lower()} issue.",
                "sources": sources,
                "size": c.get("size"),
                "generated_by": "llm",
            })

        for c in clusters:
            if c["cluster_id"] in seen_cluster_ids:
                continue
            issue_type = infer_issue_type(c["keywords"])
            urgency = infer_urgency(c["size"])
            sources = fetch_sources_for_cluster(c["cluster_id"])
            proposal = {
                "cluster_id": c["cluster_id"],
                "issue_type": issue_type,
                "urgency": urgency,
                "location": {
                    "lat": c["centroid_lat"],
                    "lon": c["centroid_lng"],
                    "confidence": c.get("location_confidence"),
                    "precision_meters": c.get("location_precision_meters"),
                    "method": "cluster_centroid",
                },
                "summary": f"{issue_type} issues clustered from citizen complaints (size: {c['size']}).",
                "recommendations": proposal_recommendations(issue_type),
                "funding_sources": [
                    "Municipal budget",
                    "State infrastructure grants",
                    "Public-private partnerships",
                ],
                "estimated_budget": infer_budget(c["size"]),
                "communication_plan": proposal_communication_plan(issue_type),
                "responsible_agencies": responsible_agencies(issue_type),
                "impact_rationale": impact_rationale(issue_type, c["size"]),
                "sources": sources,
                "size": c["size"],
                "generated_by": "heuristic_fallback",
            }
            proposals.append(proposal)
        return {"proposals": proposals[:limit]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/proposals/generate/{cluster_id}")
async def generate_proposal_for_cluster_endpoint(cluster_id: str):
    """Generate a Groq-powered proposal for a specific cluster on demand."""
    create_tables()

    try:
        from proposals import generate_proposal_for_cluster, store_proposal

        cluster_data = None
        member_threads = []

        with db.engine.connect() as conn:
            result = conn.execute(
                sa.text("""
                    SELECT cluster_id, cluster_label, centroid_lat, centroid_lng, size, keywords
                    FROM cluster_results WHERE cluster_id = :cid
                """),
                {"cid": cluster_id},
            ).fetchone()

        if result:
            cluster_data = {
                "cluster_id": result[0], "cluster_label": result[1],
                "centroid_lat": result[2], "centroid_lng": result[3],
                "size": result[4], "keywords": result[5],
            }
            with db.engine.connect() as conn:
                rows = conn.execute(
                    sa.text("""SELECT d.thread_id, d.subreddit, d.title, d.content, d.upvotes
                               FROM daily_ingest d JOIN thread_cluster_map tcm ON d.thread_id = tcm.thread_id
                               WHERE tcm.cluster_id = :cid"""),
                    {"cid": cluster_id},
                ).fetchall()
            member_threads = [
                {"thread_id": r[0], "subreddit": r[1], "title": r[2], "content": r[3], "upvotes": r[4]}
                for r in rows
            ]
        else:
            clusters = fetch_latest_clusters(200)
            match = next((c for c in clusters if c["cluster_id"] == cluster_id), None)
            if not match:
                raise HTTPException(status_code=404, detail=f"Cluster {cluster_id} not found")
            cluster_data = {
                "cluster_id": match["cluster_id"],
                "cluster_label": match.get("cluster_label", 0),
                "centroid_lat": match.get("centroid_lat"),
                "centroid_lng": match.get("centroid_lng"),
                "size": match["size"],
                "keywords": match["keywords"],
            }
            threads = fetch_latest_threads(500)
            issue_type = infer_issue_type(match["keywords"])
            member_threads = [
                {"thread_id": t["id"], "subreddit": t["subreddit"], "title": t["title"],
                 "content": t["content"], "upvotes": t["upvotes"]}
                for t in threads
                if infer_issue_type(t.get("flair", "") or t.get("title", "")) == issue_type
            ]
            if not member_threads:
                member_threads = [
                    {"thread_id": t["id"], "subreddit": t["subreddit"], "title": t["title"],
                     "content": t["content"], "upvotes": t["upvotes"]}
                    for t in threads
                ][:10]

        proposal = generate_proposal_for_cluster(
            cluster_data["cluster_id"],
            cluster_data["keywords"],
            cluster_data["size"],
            cluster_data["centroid_lat"],
            cluster_data["centroid_lng"],
            member_threads,
        )

        if proposal is None:
            raise HTTPException(status_code=500, detail="Groq API failed to generate proposal")

        store_proposal(db.engine, proposal)

        sources = fetch_sources_for_cluster(cluster_id)
        return {
            "proposal": {
                "cluster_id": proposal["cluster_id"],
                "issue_type": proposal.get("issue_type", ""),
                "urgency": proposal.get("urgency", "low"),
                "location": {
                    "lat": cluster_data["centroid_lat"] or 0,
                    "lon": cluster_data["centroid_lng"] or 0,
                    "method": "cluster_centroid",
                },
                "summary": proposal.get("summary", ""),
                "recommendations": proposal.get("recommendations", []),
                "funding_sources": proposal.get("funding_sources", []),
                "estimated_budget": proposal.get("estimated_budget", ""),
                "communication_plan": proposal.get("communication_plan")
                    or proposal_communication_plan(proposal.get("issue_type", "")),
                "responsible_agencies": proposal.get("responsible_agencies")
                    or responsible_agencies(proposal.get("issue_type", "")),
                "impact_rationale": proposal.get("impact_rationale")
                    or impact_rationale(proposal.get("issue_type", ""), cluster_data["size"]),
                "sources": sources,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/research/{cluster_id}")
async def research_cluster_stream(cluster_id: str):
    """Stream research pipeline steps as SSE."""
    create_tables()

    async def event_stream():
        from research import run_research
        for step in run_research(cluster_id, db.engine):
            yield f"data: {json.dumps(step)}\n\n"
            await asyncio.sleep(0.1)
        yield "data: {\"step\": \"done\"}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/agent-runs/{cluster_id}")
async def get_agent_runs(cluster_id: str, limit: int = 5):
    """Return recent persisted agent runs and tool traces for a cluster."""
    create_tables()
    try:
        with db.engine.connect() as conn:
            runs = conn.execute(
                sa.text("""
                    SELECT run_id, status, started_at, finished_at
                    FROM agent_runs
                    WHERE cluster_id = :cid
                    ORDER BY started_at DESC
                    LIMIT :lim
                """),
                {"cid": cluster_id, "lim": limit},
            ).fetchall()
            run_ids = [r[0] for r in runs]
            if not run_ids:
                return {"runs": []}
            steps = conn.execute(
                sa.text("""
                    SELECT run_id, step_name, tool_name, status, input_json, output_json, created_at
                    FROM agent_steps
                    WHERE run_id IN :run_ids
                    ORDER BY created_at ASC
                """).bindparams(sa.bindparam("run_ids", expanding=True)),
                {"run_ids": run_ids},
            ).fetchall()
        steps_by_run: dict[str, list[dict]] = {}
        for step in steps:
            steps_by_run.setdefault(step[0], []).append({
                "step_name": step[1],
                "tool_name": step[2],
                "status": step[3],
                "input": json.loads(step[4]) if step[4] else {},
                "output": json.loads(step[5]) if step[5] else {},
                "created_at": step[6] if step[6] else None,
            })
        return {
            "runs": [
                {
                    "run_id": run[0],
                    "status": run[1],
                    "started_at": run[2] if run[2] else None,
                    "finished_at": run[3] if run[3] else None,
                    "steps": steps_by_run.get(run[0], []),
                }
                for run in runs
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/research/{cluster_id}/download/{doc_id}")
async def download_research_report(cluster_id: str, doc_id: str):
    """Download the generated research report as markdown."""
    create_tables()
    try:
        from research import run_research
        doc = None
        for step in run_research(cluster_id, db.engine):
            if step.get("step") == "document" and step["status"] == "done":
                doc = step["output"]
                break
        if not doc:
            raise HTTPException(status_code=404, detail="No document found")
        return Response(
            content=doc,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=conflux-report-{cluster_id}.md"},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
