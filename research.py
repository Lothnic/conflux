"""
Research pipeline for deep-dive cluster analysis.
Steps: satellite context, POI identification, policy analysis, document generation.
Uses Groq LLM for knowledge-based research (no external API keys needed).
"""

import os
import json
import uuid
import logging
import sqlalchemy as sa
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("conflux.research")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


def _call_groq(system: str, user: str, temp: float = 0.3) -> str:
    payload = json.dumps({
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temp,
    }).encode()
    req = Request(GROQ_API_URL, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {GROQ_API_KEY}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "Conflux/0.1")
    resp = urlopen(req, timeout=90)
    data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"]


def run_research(cluster_id: str, engine: sa.Engine):
    """Run the full research pipeline and yield step-by-step results."""
    lat, lng, size, keywords = None, None, 0, ""

    with engine.connect() as conn:
        cluster = conn.execute(
            sa.text("SELECT centroid_lat, centroid_lng, size, keywords FROM cluster_results WHERE cluster_id = :cid"),
            {"cid": cluster_id},
        ).fetchone()

    if cluster:
        lat, lng, size, keywords = cluster[0], cluster[1], cluster[2], cluster[3]
    else:
        try:
            from pathlib import Path
            import json as _json
            p = Path("data/local_clusters.json")
            if p.exists():
                with open(p) as f:
                    clusters = _json.load(f)
                for c in clusters:
                    if c.get("cluster_id") == cluster_id:
                        lat = c.get("centroid_lat")
                        lng = c.get("centroid_lng")
                        size = c.get("size", 10)
                        keywords = c.get("keywords", cluster_id)
                        break
        except Exception:
            pass

    if lat is None and lng is None:
        lat, lng = 28.6139, 77.2090
    if not keywords:
        keywords = cluster_id

    if size == 0:
        size = 5

    yield {"step": "satellite", "status": "running", "label": "Analyzing satellite imagery...", "output": ""}
    sat_output = _call_groq(
        "You are a geospatial analyst examining Delhi via satellite imagery. "
        f"Given coordinates ({lat:.5f}, {lng:.5f}) in Delhi, India, describe what visible features would appear in satellite imagery: "
        "land use patterns, building density, green cover, water bodies, road networks. "
        "Return a 3-4 sentence markdown paragraph.",
        f"Cluster keywords: {keywords}\nCluster size: {size} complaints\nDescribe satellite context at {lat:.5f},{lng:.5f} in Delhi.",
    )
    yield {"step": "satellite", "status": "done", "label": "Satellite context analyzed", "output": sat_output.strip()}

    yield {"step": "poi", "status": "running", "label": "Identifying nearby points of interest...", "output": ""}
    poi_output = _call_groq(
        "You are a Delhi urban mapping expert. Given coordinates in Delhi, list nearby government buildings, "
        "hospitals, schools, markets, metro stations, and landmarks within 2km. "
        "Return as markdown bullet list with approximate distances.",
        f"Coordinates: {lat:.5f}, {lng:.5f}\nCluster about: {keywords}\nList 5-8 nearby POIs with distances.",
    )
    yield {"step": "poi", "status": "done", "label": "Points of interest identified", "output": poi_output.strip()}

    yield {"step": "policy", "status": "running", "label": "Analyzing applicable policies...", "output": ""}
    policy_output = _call_groq(
        "You are a Delhi municipal policy expert. Given an infrastructure cluster, identify which Delhi government "
        "policies, schemes, and agencies apply. Include: relevant MCD/PWD/DJB departments, central schemes (AMRUT, "
        "Smart Cities, Swachh Bharat), Delhi-specific acts and bylaws. Return as markdown with section headers.",
        f"Cluster keywords: {keywords}\nCluster size: {size}\nLocation: {lat:.5f}, {lng:.5f}\n"
        f"Identify applicable policies, schemes, and responsible agencies.",
    )
    yield {"step": "policy", "status": "done", "label": "Policy analysis complete", "output": policy_output.strip()}

    yield {"step": "document", "status": "running", "label": "Generating downloadable report...", "output": ""}

    proposal_row = None
    with engine.connect() as conn:
        proposal_row = conn.execute(
            sa.text("SELECT summary, recommendations, funding_sources, estimated_budget, urgency, issue_type, communication_plan, responsible_agencies, impact_rationale FROM llm_proposals WHERE cluster_id = :cid ORDER BY created_at DESC LIMIT 1"),
            {"cid": cluster_id},
        ).fetchone()

    if proposal_row:
        doc = _generate_document(cluster_id, lat, lng, keywords, size, proposal_row, sat_output, poi_output, policy_output)
    else:
        doc = _generate_document_basic(cluster_id, lat, lng, keywords, size, sat_output, poi_output, policy_output)

    doc_id = uuid.uuid4().hex[:12]
    yield {"step": "document", "status": "done", "label": "Report ready", "output": doc, "doc_id": doc_id, "download_url": f"/api/research/{cluster_id}/download/{doc_id}"}


def _generate_document(cluster_id, lat, lng, keywords, size, proposal, sat, poi, policy):
    summary = proposal[0] or ""
    recs_raw = proposal[1]
    funds_raw = proposal[2]
    budget = proposal[3] or ""
    urgency = (proposal[4] or "medium") if len(proposal) > 4 else "medium"
    issue_type = (proposal[5] or "General Infrastructure") if len(proposal) > 5 else "General Infrastructure"
    complan_raw = proposal[6] if len(proposal) > 6 else None
    agencies_raw = proposal[7] if len(proposal) > 7 else None
    impact_rationale = (proposal[8] or "") if len(proposal) > 8 else ""

    def _as_list(raw):
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                return []
        return raw or []

    recs = _as_list(recs_raw)
    funds = _as_list(funds_raw)
    complan = _as_list(complan_raw)
    agencies = _as_list(agencies_raw)

    rec_md = "\n".join(f"- {r}" for r in recs)
    funds_md = "\n".join(f"- {f}" for f in funds)
    agencies_md = "\n".join(f"- {a}" for a in agencies)
    # Communication plan is sequenced — render as an ordered list.
    complan_md = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(complan))

    # Optional sections only appear when the data is present.
    rationale_section = f"\n## Why This Urgency\n\n{impact_rationale}\n" if impact_rationale else ""
    agencies_section = f"\n## Responsible Agencies\n\n{agencies_md}\n" if agencies else ""
    complan_section = f"\n## Communication & Outreach Plan\n\n{complan_md}\n" if complan else ""

    return f"""# Conflux Infrastructure Research Report

**Cluster ID:** {cluster_id}
**Issue Type:** {issue_type}
**Urgency:** {urgency.upper()}
**Location:** {lat:.5f}, {lng:.5f}
**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
**Cluster Size:** {size} citizen complaints

---

## Executive Summary

{summary}
{rationale_section}
## Satellite Context

{sat}

## Nearby Points of Interest

{poi}

## Policy Analysis

{policy}

## Recommendations

{rec_md}
{agencies_section}{complan_section}
## Funding Sources

{funds_md}

## Estimated Budget

{budget}

---

*Generated by Conflux — Civic Intelligence for Delhi NCR*
"""


def _generate_document_basic(cluster_id, lat, lng, keywords, size, sat, poi, policy):
    return f"""# Conflux Infrastructure Research Report

**Cluster ID:** {cluster_id}
**Location:** {lat:.5f}, {lng:.5f}
**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
**Cluster Size:** {size} citizen complaints

---

## Satellite Context

{sat}

## Nearby Points of Interest

{poi}

## Policy Analysis

{policy}

---

*Generated by Conflux — Civic Intelligence for Delhi NCR*
"""
