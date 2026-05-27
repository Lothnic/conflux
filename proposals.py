"""
LLM-powered proposal generation using Groq API.
Replaces the heuristic keyword-matching baseline with actual LLM output.
"""

import os
import json
import logging
import sqlalchemy as sa
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("conflux.proposals")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are a senior urban infrastructure analyst and municipal budget planner for the city of Delhi, India.
You analyze clusters of citizen complaints and generate detailed, actionable infrastructure proposals.

Given a cluster of citizen complaints about infrastructure issues, generate a comprehensive proposal.
Output MUST be valid JSON with these exact keys:

- issue_type: string (one of "Road & Traffic", "Sanitation", "Water & Drainage", "Public Lighting", "Public Space & Environment", "General Infrastructure")
- urgency: string ("low", "medium", or "high") — based on complaint volume, severity of language, and public safety risk
- summary: string (3-4 sentence executive summary of the problem, its impact on citizens, and what needs to be done)
- recommendations: array of strings (4-6 concrete, actionable recommendations with specific Delhi-relevant context — mention areas, agencies like MCD/PWD/DJB, timelines)
- funding_sources: array of strings (3-5 realistic funding sources: "MCD Annual Budget", "Delhi Urban Development Fund", "AMRUT 2.0 Scheme", "Smart Cities Mission", "MLA-LAD Fund", "Public-Private Partnership", "NCR Planning Board Grant")
- estimated_budget: string (detailed INR breakdown like "₹12.5 lakhs (Survey: ₹1.5L, Repairs: ₹8L, Drainage: ₹2L, Contingency: ₹1L)")
- sources: array of objects with {id, subreddit, title} from the input threads provided

CRITICAL RULES:
- All costs MUST be in INR (₹), not USD or any other currency
- Be specific about Delhi locations, agencies, and context
- Estimated budgets should be detailed with component-wise breakdown
- Use Indian government scheme names and Delhi municipal structures
- Urgency should reflect actual citizen sentiment from the complaints
- Only return the JSON object, no markdown or explanatory text."""


def build_prompt(cluster_keywords: str, cluster_size: int, cluster_lat: float | None,
                  cluster_lng: float | None, threads: list[dict]) -> str:
    thread_summaries = "\n".join(
        f"- [{t.get('thread_id', '?')}] (r/{t.get('subreddit', 'delhi')}) upvotes: {t.get('upvotes', 0)}\n  Title: {t.get('title', '')}\n  Content: {(t.get('content', '') or '')[:300]}"
        for t in threads[:15]
    )

    location_info = ""
    if cluster_lat is not None and cluster_lng is not None:
        location_info = f"\nCluster centroid: lat={cluster_lat:.4f}, lng={cluster_lng:.4f} (this is in Delhi, India)"

    return f"""Cluster size: {cluster_size} citizen complaints
Cluster keywords (from ML clustering): {cluster_keywords}{location_info}

Citizen complaints in this cluster:
{thread_summaries}

Analyze these complaints from Delhi citizens and generate a detailed infrastructure proposal.
Consider the real Delhi context — which municipal zones, which specific agencies handle this, what schemes apply.
Provide a component-wise INR budget breakdown that's realistic for Delhi municipal projects."""



def call_groq(system_prompt: str, user_prompt: str) -> dict | None:
    if not GROQ_API_KEY:
        log.warning("GROQ_API_KEY not set. Cannot generate LLM proposals.")
        return None

    payload = json.dumps({
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }).encode()

    req = Request(GROQ_API_URL, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {GROQ_API_KEY}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "Conflux/0.1")

    try:
        resp = urlopen(req, timeout=60)
        data = json.loads(resp.read().decode())
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except (URLError, HTTPError, json.JSONDecodeError, KeyError) as e:
        log.error(f"Groq API call failed: {e}")
        return None


def generate_proposal_for_cluster(cluster_id: str, cluster_keywords: str, cluster_size: int,
                                   cluster_lat: float | None, cluster_lng: float | None,
                                   threads: list[dict]) -> dict | None:
    user_prompt = build_prompt(cluster_keywords, cluster_size, cluster_lat, cluster_lng, threads)
    result = call_groq(SYSTEM_PROMPT, user_prompt)
    if result is None:
        return None

    result["cluster_id"] = cluster_id
    result["centroid_lat"] = cluster_lat
    result["centroid_lng"] = cluster_lng
    if "sources" not in result:
        result["sources"] = [
            {"id": t.get("thread_id", ""), "subreddit": t.get("subreddit", "delhi"), "title": t.get("title", "")}
            for t in threads[:5]
        ]
    return result


def store_proposal(engine: sa.Engine, proposal: dict) -> bool:
    import uuid
    proposal_id = uuid.uuid4().hex[:16]

    try:
        with engine.begin() as conn:
            conn.execute(
                sa.text("""
                    INSERT OR IGNORE INTO llm_proposals
                    (proposal_id, cluster_id, issue_type, urgency, summary, recommendations,
                     funding_sources, estimated_budget, centroid_lat, centroid_lng)
                    VALUES (:pid, :cid, :issue, :urg, :sum, :recs, :funds, :budget, :clat, :clng)
                """),
                {
                    "pid": proposal_id,
                    "cid": proposal["cluster_id"],
                    "issue": proposal.get("issue_type", ""),
                    "urg": proposal.get("urgency", "low"),
                    "sum": proposal.get("summary", ""),
                    "recs": json.dumps(proposal.get("recommendations", [])),
                    "funds": json.dumps(proposal.get("funding_sources", [])),
                    "budget": proposal.get("estimated_budget", ""),
                    "clat": proposal.get("centroid_lat"),
                    "clng": proposal.get("centroid_lng"),
                },
            )
        log.info(f"Stored proposal {proposal_id} for cluster {proposal['cluster_id']}")
        return True
    except Exception as e:
        log.error(f"Failed to store proposal: {e}")
        return False


def fetch_stored_proposals(engine: sa.Engine, limit: int = 50) -> list[dict]:
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text("""
                    SELECT proposal_id, cluster_id, issue_type, urgency, summary,
                           recommendations, funding_sources, estimated_budget, centroid_lat, centroid_lng
                    FROM llm_proposals
                    ORDER BY created_at DESC
                    LIMIT :lim
                """),
                {"lim": limit},
            ).fetchall()
        seen = set()
        proposals = []
        for r in rows:
            cid = r[1]
            if cid in seen:
                continue
            seen.add(cid)
            proposals.append({
                "proposal_id": r[0],
                "cluster_id": cid,
                "issue_type": r[2],
                "urgency": r[3],
                "summary": r[4],
                "recommendations": json.loads(r[5]) if r[5] else [],
                "funding_sources": json.loads(r[6]) if r[6] else [],
                "estimated_budget": r[7],
                "centroid_lat": r[8],
                "centroid_lng": r[9],
            })
        return proposals
    except Exception as e:
        log.error(f"Failed to fetch stored proposals: {e}")
        return []
