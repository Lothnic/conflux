"""
LLM-powered proposal generation using Groq API.
Replaces the heuristic keyword-matching baseline with actual LLM output.
"""

import json
import logging
import time
import sqlalchemy as sa
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from app.core.config import settings

log = logging.getLogger("conflux.proposals")

GROQ_API_KEY = settings.groq_api_key
GROQ_MODEL = settings.groq_model
GROQ_API_URL = settings.groq_api_url

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
- responsible_agencies: array of strings (the specific Delhi bodies/departments that own this fix, e.g. "Municipal Corporation of Delhi (MCD)", "Public Works Department (PWD)", "Delhi Jal Board (DJB)", "Delhi Traffic Police", "DDA")
- communication_plan: array of strings (3-5 SEQUENCED stakeholder-outreach steps, each stating WHO to notify, the CHANNEL, and TIMING — e.g. "Week 1: File formal grievance with MCD ward office via PGMS portal", "Week 2: Brief the local RWA and area councillor", "Week 3: Issue press note to local Delhi dailies; escalate to LG office if unaddressed")
- impact_rationale: string (1-2 sentences justifying the assigned urgency, including a rough estimate of citizens affected)
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



GROQ_MAX_ATTEMPTS = 3
GROQ_429_BACKOFF_SECONDS = [5, 15, 30]


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

    for attempt in range(GROQ_MAX_ATTEMPTS):
        req = Request(GROQ_API_URL, data=payload, method="POST")
        req.add_header("Authorization", f"Bearer {GROQ_API_KEY}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "Conflux/0.1")

        try:
            resp = urlopen(req, timeout=90)
            data = json.loads(resp.read().decode())
            choice = data["choices"][0]
            content = choice["message"]["content"]
            if not content:
                # Reasoning models can burn the whole budget on reasoning.
                log.warning("Groq returned empty content (finish_reason=%s).", choice.get("finish_reason"))
                return None
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                log.warning("Groq returned a %s instead of a JSON object; rejecting.", type(parsed).__name__)
                return None
            return parsed
        except HTTPError as e:
            if e.code == 429 and attempt < GROQ_MAX_ATTEMPTS - 1:
                retry_after = None
                try:
                    retry_after = int(e.headers.get("Retry-After")) if e.headers else None
                except (TypeError, ValueError):
                    retry_after = None
                wait = retry_after if retry_after and 0 < retry_after <= 120 else GROQ_429_BACKOFF_SECONDS[min(attempt, len(GROQ_429_BACKOFF_SECONDS) - 1)]
                log.warning("Groq rate limited (429); retrying in %ss (attempt %d/%d).", wait, attempt + 1, GROQ_MAX_ATTEMPTS)
                time.sleep(wait)
                continue
            log.error(f"Groq API call failed: {e}")
            return None
        except (URLError, json.JSONDecodeError, KeyError, TypeError) as e:
            log.error(f"Groq API call failed: {e}")
            return None
    return None


def generate_proposal_for_cluster(cluster_id: str, cluster_keywords: str, cluster_size: int,
                                   cluster_lat: float | None, cluster_lng: float | None,
                                   threads: list[dict]) -> dict | None:
    user_prompt = build_prompt(cluster_keywords, cluster_size, cluster_lat, cluster_lng, threads)
    result = call_groq(SYSTEM_PROMPT, user_prompt)
    if not isinstance(result, dict):
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
                sa.text("DELETE FROM llm_proposals WHERE cluster_id = :cid"),
                {"cid": proposal["cluster_id"]},
            )
            conn.execute(
                sa.text("""
                    INSERT INTO llm_proposals
                    (proposal_id, cluster_id, issue_type, urgency, summary, recommendations,
                     funding_sources, estimated_budget, communication_plan, responsible_agencies,
                     impact_rationale, centroid_lat, centroid_lng)
                    VALUES (:pid, :cid, :issue, :urg, :sum, :recs, :funds, :budget, :complan,
                            :agencies, :rationale, :clat, :clng)
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
                    "complan": json.dumps(proposal.get("communication_plan", [])),
                    "agencies": json.dumps(proposal.get("responsible_agencies", [])),
                    "rationale": proposal.get("impact_rationale", ""),
                    "clat": proposal.get("centroid_lat"),
                    "clng": proposal.get("centroid_lng"),
                },
            )
        log.info(f"Stored proposal {proposal_id} for cluster {proposal['cluster_id']}")
        return True
    except Exception as e:
        log.error(f"Failed to store proposal: {e}")
        return False


def _decode_json_column(value) -> list:
    """Decode a JSON list column that may be TEXT (str) or JSONB (already a list)."""
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        decoded = json.loads(value)
        return decoded if isinstance(decoded, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def fetch_stored_proposals(engine: sa.Engine, limit: int = 50) -> list[dict]:
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text("""
                    SELECT lp.proposal_id, lp.cluster_id, lp.issue_type, lp.urgency, lp.summary,
                           lp.recommendations, lp.funding_sources, lp.estimated_budget,
                           lp.communication_plan, lp.responsible_agencies, lp.impact_rationale,
                           lp.centroid_lat, lp.centroid_lng,
                           cr.location_confidence, cr.location_precision_meters
                    FROM llm_proposals lp
                    LEFT JOIN cluster_results cr ON lp.cluster_id = cr.cluster_id
                    ORDER BY lp.created_at DESC
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
                "recommendations": _decode_json_column(r[5]),
                "funding_sources": _decode_json_column(r[6]),
                "estimated_budget": r[7],
                "communication_plan": _decode_json_column(r[8]),
                "responsible_agencies": _decode_json_column(r[9]),
                "impact_rationale": r[10] or "",
                "centroid_lat": r[11],
                "centroid_lng": r[12],
                "location_confidence": r[13],
                "location_precision_meters": r[14],
            })
        return proposals
    except Exception as e:
        log.error(f"Failed to fetch stored proposals: {e}")
        return []
