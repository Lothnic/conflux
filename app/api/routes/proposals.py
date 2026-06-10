"""
Proposal-related endpoints — heuristic fallback + LLM-powered generation.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
import sqlalchemy as sa

from app.core.database import DEMO_MODE, database_available, engine, init_db_sync
from app.services.cluster_service import fetch_latest_clusters, fetch_sources_for_cluster
from app.services.thread_service import fetch_latest_threads
from app.services.proposal_heuristics import (
    infer_issue_type,
    infer_urgency,
    infer_budget,
    proposal_recommendations,
    responsible_agencies,
    proposal_communication_plan,
    impact_rationale,
)

router = APIRouter()


@router.get("/proposals")
async def get_proposals(limit: int = 50):
    """Return generated infrastructure proposals (LLM-powered with heuristic fallback)."""
    init_db_sync()

    try:
        from proposals import fetch_stored_proposals

        stored = fetch_stored_proposals(engine, limit)
        if not DEMO_MODE:
            stored = [p for p in stored if not str(p["cluster_id"]).startswith("demo-")]

        clusters = fetch_latest_clusters(limit)
        if not DEMO_MODE:
            clusters = [c for c in clusters if not str(c["cluster_id"]).startswith("demo-")]
        clusters_by_id = {c["cluster_id"]: c for c in clusters}
        proposals = []
        seen_cluster_ids: set[str] = set()

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


@router.post("/proposals/generate/{cluster_id}")
async def generate_proposal_for_cluster_endpoint(cluster_id: str):
    """Generate a Groq-powered proposal for a specific cluster on demand."""
    init_db_sync()

    try:
        from proposals import generate_proposal_for_cluster, store_proposal

        cluster_data = None
        member_threads: list[dict] = []

        with engine.connect() as conn:
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
            with engine.connect() as conn:
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
                "cluster_id": match["cluster_id"], "cluster_label": match.get("cluster_label", 0),
                "centroid_lat": match.get("centroid_lat"), "centroid_lng": match.get("centroid_lng"),
                "size": match["size"], "keywords": match["keywords"],
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

        store_proposal(engine, proposal)

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
