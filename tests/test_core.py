import json
import sys
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db
from main import (
    impact_rationale,
    infer_budget,
    infer_issue_type,
    infer_urgency,
    proposal_communication_plan,
    responsible_agencies,
)
from proposals import fetch_stored_proposals, store_proposal
from policy_retriever import retrieve_policy
from worker import ingest_and_cluster as worker


def create_sqlite_test_engine():
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys = ON"))
        for stmt in db.SQLITE_CREATE_TABLES_SQL.strip().split(";"):
            if stmt.strip():
                conn.execute(sa.text(stmt))
    return engine


def test_schema_includes_geolocation_quality_columns():
    engine = create_sqlite_test_engine()
    with engine.connect() as conn:
        thread_geo_cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(thread_geo)"))}
        cluster_cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(cluster_results)"))}
        run_cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(agent_runs)"))}
        step_cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(agent_steps)"))}

    assert "location_method" in thread_geo_cols
    assert "location_confidence" in thread_geo_cols
    assert "location_precision_meters" in thread_geo_cols
    assert "geocoder_query" in thread_geo_cols
    assert "location_confidence" in cluster_cols
    assert "location_precision_meters" in cluster_cols
    assert {"run_id", "cluster_id", "status"}.issubset(run_cols)
    assert {"run_id", "step_name", "tool_name", "input_json", "output_json"}.issubset(step_cols)


def test_policy_retriever_returns_relevant_docs():
    hits = retrieve_policy("broken traffic signal pedestrian crossing near school", limit=2)
    assert hits
    assert any("Road" in hit.title or "Traffic" in hit.title for hit in hits)


def test_geolocation_precision_mapping():
    assert worker.precision_to_meters("landmark") == 80
    assert worker.precision_to_meters("intersection") == 120
    assert worker.precision_to_meters("neighborhood") == 900
    assert worker.precision_to_meters("unresolved") is None


def test_low_confidence_location_does_not_fallback_to_city(monkeypatch):
    monkeypatch.setattr(worker, "GEOCODE_ENABLED", True)
    monkeypatch.setattr(worker, "GEOCODE_CITY_FALLBACK_ENABLED", False)
    monkeypatch.setattr(
        worker,
        "extract_location_candidate",
        lambda title, content: {
            "location_text": "",
            "confidence": 0,
            "precision": "unresolved",
            "reason": "No location mentioned",
        },
    )

    geo = worker.resolve_location("Pothole problem", "Please fix this")

    assert geo["lat"] is None
    assert geo["lng"] is None
    assert geo["location_method"] == "ai_place_extraction"


def test_issue_heuristics_cover_expected_categories():
    assert infer_issue_type("broken traffic signal and pothole") == "Road & Traffic"
    assert infer_issue_type("trash and garbage dump") == "Sanitation"
    assert infer_issue_type("sewer drain flood") == "Water & Drainage"
    assert infer_issue_type("streetlight dark lane") == "Public Lighting"
    assert infer_issue_type("park pollution noise") == "Public Space & Environment"
    assert infer_issue_type("misc request") == "General Infrastructure"


def test_priority_and_budget_thresholds():
    assert infer_urgency(20) == "high"
    assert infer_urgency(8) == "medium"
    assert infer_urgency(7) == "low"
    assert infer_budget(20) == "$250k-$1M"
    assert infer_budget(8) == "$50k-$250k"
    assert infer_budget(7) == "$10k-$50k"


def test_new_structured_output_heuristics():
    # Responsible agencies are issue-specific and never empty.
    assert "Delhi Jal Board (DJB)" in responsible_agencies("Water & Drainage")
    assert responsible_agencies("Unknown Type")  # falls back to a default list

    # Communication plan is a non-empty sequence naming the lead agency.
    plan = proposal_communication_plan("Road & Traffic")
    assert len(plan) >= 3
    assert any("Public Works Department (PWD)" in step for step in plan)

    # Impact rationale reflects the urgency tier and scales with cluster size.
    assert "high" in impact_rationale("Sanitation", 25).lower()
    assert "low" in impact_rationale("Sanitation", 2).lower()


def test_store_proposal_replaces_existing_cluster_proposal():
    engine = create_sqlite_test_engine()
    base = {
        "cluster_id": "cluster-1",
        "issue_type": "Road & Traffic",
        "urgency": "medium",
        "summary": "Initial summary",
        "recommendations": ["Survey road"],
        "funding_sources": ["Municipal budget"],
        "estimated_budget": "$10k-$50k",
        "communication_plan": ["Week 1: File grievance"],
        "responsible_agencies": ["Public Works Department (PWD)"],
        "impact_rationale": "Medium urgency: affects local commuters.",
        "centroid_lat": 28.6,
        "centroid_lng": 77.2,
    }

    assert store_proposal(engine, base)
    assert store_proposal(engine, {**base, "summary": "Updated summary"})

    rows = fetch_stored_proposals(engine)
    assert len(rows) == 1
    assert rows[0]["summary"] == "Updated summary"
    assert rows[0]["recommendations"] == ["Survey road"]
    # New structured outputs round-trip through JSON storage.
    assert rows[0]["communication_plan"] == ["Week 1: File grievance"]
    assert rows[0]["responsible_agencies"] == ["Public Works Department (PWD)"]
    assert rows[0]["impact_rationale"] == "Medium urgency: affects local commuters."

    with engine.connect() as conn:
        stored_json = conn.execute(
            sa.text("SELECT recommendations FROM llm_proposals WHERE cluster_id = :cid"),
            {"cid": "cluster-1"},
        ).scalar_one()
    assert json.loads(stored_json) == ["Survey road"]
