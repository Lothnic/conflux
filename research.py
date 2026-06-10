"""
Agentic research pipeline for deep-dive cluster analysis.

The SSE endpoint streams this as tool-like agent steps:
1. Load issue context
2. Inspect geolocation quality
3. Gather nearby urban context
4. Retrieve policy and agency constraints
5. Reason over stakeholders, feasibility, cost, and risk
6. Generate an evidence-backed planning memo
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

import sqlalchemy as sa
from dotenv import load_dotenv
from policy_retriever import retrieve_policy

load_dotenv()

log = logging.getLogger("conflux.research")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OVERPASS_ENABLED = os.getenv("OVERPASS_ENABLED", "0") == "1"
OVERPASS_URL = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")


@dataclass
class AgentState:
    cluster_id: str
    lat: float | None = None
    lng: float | None = None
    size: int = 0
    keywords: str = ""
    location_confidence: float | None = None
    location_precision_meters: int | None = None
    issue_type: str = "General Infrastructure"
    urgency: str = "medium"
    proposal: dict[str, Any] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    doc: str = ""
    run_id: str = ""


def _event(step: str, status: str, label: str, output: str = "", **extra: Any) -> dict[str, Any]:
    return {"step": step, "status": status, "label": label, "output": output, **extra}


def _start_run(engine: sa.Engine, cluster_id: str) -> str:
    run_id = uuid.uuid4().hex[:16]
    with engine.begin() as conn:
        conn.execute(
            sa.text("""
                INSERT INTO agent_runs (run_id, cluster_id, status)
                VALUES (:rid, :cid, 'running')
            """),
            {"rid": run_id, "cid": cluster_id},
        )
    return run_id


def _finish_run(engine: sa.Engine, run_id: str, status: str = "complete") -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text("""
                UPDATE agent_runs
                SET status = :status, finished_at = CURRENT_TIMESTAMP
                WHERE run_id = :rid
            """),
            {"status": status, "rid": run_id},
        )


def _persist_step(
    engine: sa.Engine,
    run_id: str,
    step_name: str,
    tool_name: str,
    status: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
) -> None:
    with engine.begin() as conn:
        conn.execute(
            sa.text("""
                INSERT INTO agent_steps
                (step_id, run_id, step_name, tool_name, status, input_json, output_json)
                VALUES (:sid, :rid, :step, :tool, :status, :input, :output)
            """),
            {
                "sid": uuid.uuid4().hex[:16],
                "rid": run_id,
                "step": step_name,
                "tool": tool_name,
                "status": status,
                "input": json.dumps(input_payload, ensure_ascii=False),
                "output": json.dumps(output_payload, ensure_ascii=False),
            },
        )


def _safe_json_loads(raw: Any) -> list[Any]:
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return value if isinstance(value, list) else []
        except json.JSONDecodeError:
            return []
        return raw if isinstance(raw, list) else []


def _source_markdown(src: dict[str, Any]) -> str:
    title = str(src.get("title") or src.get("id") or "Source").replace("[", "\\[").replace("]", "\\]")
    url = _citation_url(src)
    provider = src.get("source") or "source"
    upvotes = src.get("upvotes", 0)
    prefix = f"[{src.get('id', 'source')}] "
    if url:
        return f"- {prefix}[{title}]({url}) ({provider}, {upvotes} upvotes)"
    return f"- {prefix}{title} ({provider}, {upvotes} upvotes)"


def _citation_url(src: dict[str, Any]) -> str:
    url = src.get("url")
    if url:
        return str(url)
    provider = str(src.get("source") or "")
    thread_id = str(src.get("id") or "")
    if thread_id and provider and not provider.startswith(("news:", "gov:")):
        return f"https://reddit.com/r/{provider}/comments/{thread_id}"
    return ""


def _source_tool_output(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "- No linked source rows available."
    return "\n".join(_source_markdown(src) for src in sources)


def _call_llm(system: str, user: str, temp: float = 0.25, fallback: str = "") -> str:
    if not GROQ_API_KEY:
        return fallback

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

    try:
        resp = urlopen(req, timeout=90)
        data = json.loads(resp.read().decode())
        return data["choices"][0]["message"]["content"].strip()
    except (HTTPError, URLError, KeyError, json.JSONDecodeError, TimeoutError) as exc:
        log.warning("Research LLM call failed: %s", exc)
        return fallback


def load_issue_context(state: AgentState, engine: sa.Engine) -> str:
    with engine.connect() as conn:
        cluster = conn.execute(
            sa.text("""
                SELECT cluster_id, centroid_lat, centroid_lng, size, keywords,
                       location_confidence, location_precision_meters
                FROM cluster_results
                WHERE cluster_id = :cid
            """),
            {"cid": state.cluster_id},
        ).fetchone()

        proposal = conn.execute(
            sa.text("""
                SELECT issue_type, urgency, summary, recommendations, funding_sources,
                       estimated_budget, communication_plan, responsible_agencies,
                       impact_rationale
                FROM llm_proposals
                WHERE cluster_id = :cid
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"cid": state.cluster_id},
        ).fetchone()

        source_rows = conn.execute(
            sa.text("""
                SELECT d.thread_id, d.subreddit, d.title, d.content, d.upvotes, d.url,
                       tg.location_text, tg.location_confidence, tg.location_precision_meters
                FROM daily_ingest d
                JOIN thread_cluster_map tcm ON d.thread_id = tcm.thread_id
                LEFT JOIN thread_geo tg ON d.thread_id = tg.thread_id
                WHERE tcm.cluster_id = :cid
                ORDER BY d.upvotes DESC
                LIMIT 10
            """),
            {"cid": state.cluster_id},
        ).fetchall()

    if cluster:
        state.lat = cluster[1]
        state.lng = cluster[2]
        state.size = int(cluster[3] or 0)
        state.keywords = cluster[4] or state.cluster_id
        state.location_confidence = cluster[5]
        state.location_precision_meters = cluster[6]
    else:
        _load_local_cluster_fallback(state)

    if proposal:
        state.issue_type = proposal[0] or state.issue_type
        state.urgency = proposal[1] or state.urgency
        state.proposal = {
            "summary": proposal[2] or "",
            "recommendations": _safe_json_loads(proposal[3]),
            "funding_sources": _safe_json_loads(proposal[4]),
            "estimated_budget": proposal[5] or "",
            "communication_plan": _safe_json_loads(proposal[6]),
            "responsible_agencies": _safe_json_loads(proposal[7]),
            "impact_rationale": proposal[8] or "",
        }

    state.sources = [
        {
            "id": row[0],
            "source": row[1],
            "title": row[2],
            "content": row[3] or "",
            "upvotes": int(row[4] or 0),
            "url": row[5],
            "location_text": row[6],
            "location_confidence": row[7],
            "location_precision_meters": row[8],
        }
        for row in source_rows
    ]
    state.size = state.size or len(state.sources) or 1

    output = (
        f"Loaded {state.size} linked civic report(s) for **{state.issue_type}**.\n"
        f"- Keywords: {state.keywords}\n"
        f"- Urgency: {state.urgency}\n"
        f"- Evidence sources: {len(state.sources)}\n\n"
        f"Top citations:\n{_source_tool_output(state.sources[:5])}"
    )
    state.evidence.append({"type": "issue_context", "summary": output})
    state.outputs["context"] = output
    return output


def _load_local_cluster_fallback(state: AgentState) -> None:
    from pathlib import Path

    path = Path("data/local_clusters.json")
    if not path.exists():
        return
    try:
        clusters = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    match = next((c for c in clusters if c.get("cluster_id") == state.cluster_id), None)
    if not match:
        return
    state.lat = match.get("centroid_lat")
    state.lng = match.get("centroid_lng")
    state.size = int(match.get("size") or 1)
    state.keywords = match.get("keywords") or state.cluster_id


def assess_geolocation(state: AgentState) -> str:
    if state.lat is None or state.lng is None:
        output = (
            "No reliable geocoded location is available for this issue. "
            "The agent will avoid making site-specific claims until a planner verifies the location."
        )
    else:
        confidence = state.location_confidence
        precision = state.location_precision_meters
        confidence_label = (
            "high" if confidence is not None and confidence >= 0.75
            else "medium" if confidence is not None and confidence >= 0.5
            else "low"
        )
        output = (
            f"Resolved estimated location at **{state.lat:.5f}, {state.lng:.5f}**.\n"
            f"- Confidence: {confidence_label} ({confidence if confidence is not None else 'unscored'})\n"
            f"- Precision: ~{precision}m" if precision else
            f"Resolved estimated location at **{state.lat:.5f}, {state.lng:.5f}** with {confidence_label} confidence."
        )
    state.evidence.append({"type": "geolocation", "summary": output})
    state.outputs["geolocation"] = output
    return output


def gather_nearby_context(state: AgentState) -> str:
    if state.lat is None or state.lng is None:
        output = "Nearby context skipped because the issue location is unresolved."
        state.outputs["poi"] = output
        return output

    pois = _query_overpass_pois(state.lat, state.lng)
    if pois:
        poi_md = "\n".join(f"- {p['name']} ({p['kind']}, ~{p['distance_m']}m)" for p in pois[:8])
        output = f"Nearby urban context from OpenStreetMap/Overpass:\n{poi_md}"
    else:
        fallback = (
            "No live POI API result was available. Use the mapped locality and source reports "
            "to verify schools, hospitals, parks, transit stops, markets, and civic facilities within 1-2km."
        )
        output = _call_llm(
            "You are a Delhi urban mapping analyst. Provide cautious, non-fabricated planning context.",
            f"Coordinates: {state.lat:.5f}, {state.lng:.5f}\nIssue: {state.issue_type}\nKeywords: {state.keywords}\n"
            "Describe the types of nearby facilities a planner should verify. Do not invent exact names.",
            fallback=fallback,
        )

    state.evidence.append({"type": "nearby_context", "summary": output})
    state.outputs["poi"] = output
    return output


def _query_overpass_pois(lat: float, lng: float) -> list[dict[str, Any]]:
    if not OVERPASS_ENABLED:
        return []
    query = f"""
    [out:json][timeout:15];
    (
      node(around:1500,{lat},{lng})[amenity~"school|hospital|clinic|bus_station|police|fire_station"];
      node(around:1500,{lat},{lng})[leisure="park"];
      node(around:1500,{lat},{lng})[railway="station"];
      way(around:1500,{lat},{lng})[amenity~"school|hospital|clinic|bus_station|police|fire_station"];
      way(around:1500,{lat},{lng})[leisure="park"];
      way(around:1500,{lat},{lng})[railway="station"];
    );
    out center tags 20;
    """
    try:
        req = Request(OVERPASS_URL, data=f"data={quote_plus(query)}".encode(), method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("User-Agent", "Conflux/0.1")
        payload = json.loads(urlopen(req, timeout=20).read().decode())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return []

    items = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        elat = element.get("lat") or element.get("center", {}).get("lat")
        elng = element.get("lon") or element.get("center", {}).get("lon")
        if elat is None or elng is None:
            continue
        items.append({
            "name": name,
            "kind": tags.get("amenity") or tags.get("leisure") or tags.get("railway") or "poi",
            "distance_m": int(_rough_distance_m(lat, lng, float(elat), float(elng))),
        })
    return sorted(items, key=lambda item: item["distance_m"])


def _rough_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return (((lat1 - lat2) * 111_000) ** 2 + ((lng1 - lng2) * 96_000) ** 2) ** 0.5


def retrieve_policy_context(state: AgentState) -> str:
    agencies = state.proposal.get("responsible_agencies") or _fallback_agencies(state.issue_type)
    policy_hits = retrieve_policy(f"{state.issue_type} {state.keywords} {' '.join(agencies)}", limit=3)
    policy_lines = [
        f"- Lead agency: {agencies[0]}",
        "- Planning constraints: right-of-way, ward jurisdiction, utility ownership, maintenance responsibility, and public safety risk.",
    ]
    if state.issue_type == "Road & Traffic":
        policy_lines += ["- Relevant checks: PWD/MCD road ownership, Delhi Traffic Police signal plan, pedestrian crossing standards."]
    elif state.issue_type == "Water & Drainage":
        policy_lines += ["- Relevant checks: DJB sewer responsibility, storm-water drain ownership, monsoon preparedness plan."]
    elif state.issue_type == "Sanitation":
        policy_lines += ["- Relevant checks: MCD solid-waste collection route, Swachh Bharat Urban guidelines, market association responsibilities."]
    elif state.issue_type == "Public Lighting":
        policy_lines += ["- Relevant checks: streetlight asset owner, DISCOM maintenance SLA, dark-spot safety mapping."]
    else:
        policy_lines += ["- Relevant checks: ward-level asset ownership, local bylaws, public grievance SLA."]

    if policy_hits:
        policy_lines.append("\nRetrieved policy snippets:")
        for hit in policy_hits:
            policy_lines.append(f"- **{hit.title}** (score {hit.score:.2f}): {hit.snippet[:260]}...")

    output = "\n".join(policy_lines)
    state.evidence.append({"type": "policy", "summary": output})
    state.outputs["policy"] = output
    return output


def reason_about_intervention(state: AgentState) -> str:
    fallback = (
        f"Root cause likely combines recurring {state.issue_type.lower()} asset failure, delayed maintenance, "
        "and unclear agency ownership. The recommended intervention should be phased: verify site, assign lead agency, "
        "apply a low-regret immediate fix, then fund a durable repair."
    )
    output = _call_llm(
        "You are an urban planning agent. Reason concisely using only provided evidence. Avoid unsupported claims.",
        json.dumps({
            "issue_type": state.issue_type,
            "urgency": state.urgency,
            "keywords": state.keywords,
            "size": state.size,
            "location": {"lat": state.lat, "lng": state.lng, "confidence": state.location_confidence},
            "sources": [{"title": s["title"], "upvotes": s["upvotes"]} for s in state.sources[:8]],
            "nearby_context": state.outputs.get("poi", ""),
            "policy": state.outputs.get("policy", ""),
        }, ensure_ascii=False),
        fallback=fallback,
    )
    state.evidence.append({"type": "reasoning", "summary": output})
    state.outputs["reasoning"] = output
    return output


def generate_recommendation(state: AgentState) -> str:
    recs = state.proposal.get("recommendations") or ["Conduct on-site verification", "Assign lead agency", "Implement phased repair plan"]
    budget = state.proposal.get("estimated_budget") or "Budget estimate pending site inspection"
    risks = [
        "Location confidence may require planner verification before issuing work orders.",
        "Agency ownership may delay execution if asset responsibility is disputed.",
        "Temporary fixes may fail without durable maintenance funding.",
    ]
    output = "\n".join([
        "Recommended action plan:",
        *[f"- {rec}" for rec in recs],
        f"\nEstimated cost: {budget}",
        "\nRisks:",
        *[f"- {risk}" for risk in risks],
        "\nPriority: " + state.urgency.upper(),
    ])
    state.evidence.append({"type": "recommendation", "summary": output})
    state.outputs["recommendation"] = output
    return output


def write_agent_report(state: AgentState) -> str:
    doc_id = uuid.uuid4().hex[:12]
    recs = state.proposal.get("recommendations") or []
    funds = state.proposal.get("funding_sources") or []
    agencies = state.proposal.get("responsible_agencies") or _fallback_agencies(state.issue_type)
    communications = state.proposal.get("communication_plan") or []

    state.doc = f"""# Conflux Agentic Urban Planning Report

**Cluster ID:** {state.cluster_id}
**Issue Type:** {state.issue_type}
**Priority:** {state.urgency.upper()}
**Estimated Location:** {f"{state.lat:.5f}, {state.lng:.5f}" if state.lat is not None and state.lng is not None else "Unresolved"}
**Location Confidence:** {state.location_confidence if state.location_confidence is not None else "unscored"}
**Precision:** {f"~{state.location_precision_meters}m" if state.location_precision_meters else "unknown"}
**Generated:** {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}

---

## Problem Summary

{state.proposal.get("summary") or state.outputs.get("context", "")}

## Agent Evidence

### Geolocation Assessment
{state.outputs.get("geolocation", "")}

### Nearby Context
{state.outputs.get("poi", "")}

### Policy & Agency Assessment
{state.outputs.get("policy", "")}

### Reasoning Summary
{state.outputs.get("reasoning", "")}

## Recommended Actions

{chr(10).join(f"- {rec}" for rec in recs) if recs else state.outputs.get("recommendation", "")}

## Responsible Agencies

{chr(10).join(f"- {agency}" for agency in agencies)}

## Funding Sources

{chr(10).join(f"- {fund}" for fund in funds) if funds else "- Funding source pending"}

## Communication Plan

{chr(10).join(f"{idx + 1}. {step}" for idx, step in enumerate(communications)) if communications else "1. File a consolidated grievance with the lead agency and attach evidence."}

## Evidence Sources

{_source_tool_output(state.sources)}

---

*Generated by Conflux Agent — geospatial civic intelligence for urban planners*
"""
    return doc_id


def _fallback_agencies(issue_type: str) -> list[str]:
    agency_map = {
        "Road & Traffic": ["Public Works Department (PWD)", "Delhi Traffic Police", "Municipal Corporation of Delhi (MCD)"],
        "Sanitation": ["Municipal Corporation of Delhi (MCD)", "Swachh Bharat Mission (Urban)"],
        "Water & Drainage": ["Delhi Jal Board (DJB)", "Irrigation & Flood Control Department"],
        "Public Lighting": ["Municipal Corporation of Delhi (MCD)", "BSES/Tata Power-DDL"],
        "Public Space & Environment": ["Delhi Development Authority (DDA)", "Delhi Pollution Control Committee (DPCC)"],
    }
    return agency_map.get(issue_type, ["Municipal Corporation of Delhi (MCD)"])


AgentNode = tuple[str, str, str, Callable[[AgentState], str]]


def _run_step(
    engine: sa.Engine,
    state: AgentState,
    step_name: str,
    tool_name: str,
    fn: Callable[[AgentState], str],
) -> str:
    input_payload = {
        "cluster_id": state.cluster_id,
        "issue_type": state.issue_type,
        "lat": state.lat,
        "lng": state.lng,
        "keywords": state.keywords,
    }
    output = fn(state)
    _persist_step(
        engine,
        state.run_id,
        step_name,
        tool_name,
        "done",
        input_payload,
        {"output": output},
    )
    return output


def run_research(cluster_id: str, engine: sa.Engine) -> Iterable[dict[str, Any]]:
    """Run the agentic research workflow and yield SSE-compatible step events."""
    state = AgentState(cluster_id=cluster_id, run_id=_start_run(engine, cluster_id))

    labels = {
        "context": "Loading issue context and evidence...",
        "geolocation": "Assessing geolocation confidence...",
        "poi": "Gathering nearby urban context...",
        "policy": "Retrieving policy and agency constraints...",
        "reasoning": "Reasoning over stakeholders, feasibility, and risk...",
        "recommendation": "Generating prioritized intervention plan...",
    }
    tools = {
        "context": "load_issue_context",
        "geolocation": "assess_geolocation_confidence",
        "poi": "nearby_context_tool",
        "policy": "policy_rag_retriever",
        "reasoning": "urban_reasoning_llm",
        "recommendation": "recommendation_generator",
    }

    base_steps: list[AgentNode] = [
        ("context", "load_issue_context", "context", lambda s: load_issue_context(s, engine)),
        ("geolocation", "assess_geolocation_confidence", "geolocation", assess_geolocation),
    ]
    follow_up_steps: list[AgentNode] = [
        ("policy", "policy_rag_retriever", "policy", retrieve_policy_context),
        ("reasoning", "urban_reasoning_llm", "reasoning", reason_about_intervention),
        ("recommendation", "recommendation_generator", "recommendation", generate_recommendation),
    ]

    try:
        for step, tool_name, output_key, fn in base_steps:
            yield _event(
                step,
                "running",
                labels.get(step, f"Running {step}..."),
                tool=tools.get(step, tool_name),
                run_id=state.run_id,
            )
            output = _run_step(engine, state, step, tool_name, fn)
            yield _event(
                step,
                "done",
                labels.get(step, step).replace("...", " complete"),
                output or state.outputs.get(output_key, ""),
                tool=tools.get(step, tool_name),
                run_id=state.run_id,
            )

        if state.lat is not None and state.lng is not None:
            step, tool_name, output_key, fn = ("poi", "nearby_context_tool", "poi", gather_nearby_context)
            yield _event(step, "running", labels[step], tool=tools[step], run_id=state.run_id)
            output = _run_step(engine, state, step, tool_name, fn)
            yield _event(
                step,
                "done",
                labels[step].replace("...", " complete"),
                output or state.outputs.get(output_key, ""),
                tool=tools[step],
                run_id=state.run_id,
            )
        else:
            state.outputs["poi"] = "Skipped because location is unresolved."
            yield _event(
                "poi",
                "done",
                "Skipped due to unresolved location",
                state.outputs["poi"],
                tool=tools.get("poi", "nearby_context_tool"),
                run_id=state.run_id,
            )

        for step, tool_name, output_key, fn in follow_up_steps:
            yield _event(
                step,
                "running",
                labels.get(step, f"Running {step}..."),
                tool=tools.get(step, tool_name),
                run_id=state.run_id,
            )
            output = _run_step(engine, state, step, tool_name, fn)
            yield _event(
                step,
                "done",
                labels.get(step, step).replace("...", " complete"),
                output or state.outputs.get(output_key, ""),
                tool=tools.get(step, tool_name),
                run_id=state.run_id,
            )
    except Exception as exc:
        _finish_run(engine, state.run_id, "error")
        log.exception("Agent run failed")
        yield _event("agent", "error", "Agent run failed", str(exc), run_id=state.run_id)
        return

    yield _event("document", "running", "Writing agent report...", tool="agent_report_writer", run_id=state.run_id)
    try:
        doc_id = write_agent_report(state)
        _persist_step(
            engine,
            state.run_id,
            "document",
            "agent_report_writer",
            "done",
            {"cluster_id": cluster_id},
            {"doc_id": doc_id, "chars": len(state.doc)},
        )
        _finish_run(engine, state.run_id, "complete")
        try:
            evidence = state.evidence
        except Exception as exc:
            evidence = [{"type": "evidence_error", "summary": str(exc)}]
        yield _event(
            "document",
            "done",
            "Agent report ready",
            state.doc,
            doc_id=doc_id,
            download_url=f"/api/research/{cluster_id}/download/{doc_id}",
            evidence=evidence,
            tool="agent_report_writer",
            run_id=state.run_id,
        )
    except Exception as exc:
        _finish_run(engine, state.run_id, "error")
        yield _event("document", "error", "Report generation failed", str(exc), run_id=state.run_id)
