import json

import sqlalchemy as sa

import db
from main import infer_budget, infer_issue_type, infer_urgency
from proposals import fetch_stored_proposals, store_proposal


def create_sqlite_test_engine():
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys = ON"))
        for stmt in db.SQLITE_CREATE_TABLES_SQL.strip().split(";"):
            if stmt.strip():
                conn.execute(sa.text(stmt))
    return engine


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
        "centroid_lat": 28.6,
        "centroid_lng": 77.2,
    }

    assert store_proposal(engine, base)
    assert store_proposal(engine, {**base, "summary": "Updated summary"})

    rows = fetch_stored_proposals(engine)
    assert len(rows) == 1
    assert rows[0]["summary"] == "Updated summary"
    assert rows[0]["recommendations"] == ["Survey road"]

    with engine.connect() as conn:
        stored_json = conn.execute(
            sa.text("SELECT recommendations FROM llm_proposals WHERE cluster_id = :cid"),
            {"cid": "cluster-1"},
        ).scalar_one()
    assert json.loads(stored_json) == ["Survey road"]
