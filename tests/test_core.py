import json
import sys
from pathlib import Path

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import database as db
from app.services.proposal_heuristics import (
    impact_rationale,
    infer_budget,
    infer_issue_type,
    infer_urgency,
    proposal_communication_plan,
    responsible_agencies,
)
from app.services.proposal_generator import fetch_stored_proposals, store_proposal
from app.services.policy_retriever import retrieve_policy
from worker import geocoding as worker
from worker.ingest import (
    _BASE_INFRA_KEYWORDS,
    _extra_infra_keywords,
    _gdelt_record_url,
    fetch_gdelt_threads,
    matches_infra,
)


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
    assert infer_budget(20) == "₹2-8 crore"
    assert infer_budget(8) == "₹40 lakh-₹2 crore"
    assert infer_budget(7) == "₹8-40 lakh"


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


def test_services_fallback_to_local_sample_data_without_database(monkeypatch):
    from app.services import cluster_service, thread_service

    monkeypatch.setattr(cluster_service, "DEMO_MODE", False)
    monkeypatch.setattr(cluster_service, "database_available", lambda: False)
    clusters = cluster_service.fetch_latest_clusters()

    assert clusters
    assert clusters[0]["cluster_id"].startswith("demo-")

    monkeypatch.setattr(thread_service, "DEMO_MODE", False)
    monkeypatch.setattr(thread_service, "database_available", lambda: False)
    threads = thread_service.fetch_latest_threads()

    assert threads
    assert any(thread.get("cluster_id") for thread in threads)


def test_matches_infra_covers_english_hindi_and_extras(monkeypatch):
    assert matches_infra("Massive potholes on Ring Road")
    assert matches_infra("\u0938\u0921\u093c\u0915 \u092a\u0930 \u0917\u0921\u094d\u0922\u093e \u092a\u0921\u093c\u093e \u0939\u0948")
    assert not matches_infra("Delhi weather is pleasant today")

    monkeypatch.setattr("worker.ingest.INFRA_KEYWORDS", _BASE_INFRA_KEYWORDS + ["water tanker delay"])
    assert matches_infra("Water tanker delay in Dwarka")


def test_extra_infra_keywords_env(monkeypatch):
    monkeypatch.setenv("INFRA_EXTRA_KEYWORDS", "Water Tanker Delay, billing issue ,")
    extras = _extra_infra_keywords()
    assert extras == ["water tanker delay", "billing issue"]


def test_gdelt_record_url_prefers_article_url():
    assert _gdelt_record_url({"url": "https://example.com/a", "sourceurl": "https://src.com"}) == "https://example.com/a"
    assert _gdelt_record_url({"sourceurl": "https://src.com"}) == "https://src.com"
    assert _gdelt_record_url({}) == ""


def test_gdelt_fetch_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr("worker.ingest.GDELT_ENABLED", False)
    assert fetch_gdelt_threads() == []


def test_gdelt_fetch_parses_articles(monkeypatch):
    from datetime import datetime, timedelta, timezone as tz

    # Seen-date must be inside the HOURS_BACK window regardless of when the
    # suite runs — a hardcoded date silently broke this test at midnight UTC.
    seendate = (datetime.now(tz.utc) - timedelta(hours=1)).strftime("%Y%m%dT%H%M%S") + "Z"
    payload = {
        "articles": [
            {
                "title": "Massive potholes paralyse Ring Road traffic in Delhi",
                "url": "https://example.news/potholes-ring-road",
                "domain": "example.news",
                "seendate": seendate,
                "sourcecountry": "India",
                "language": "English",
            },
            {
                "title": "Delhi weather remains pleasant",
                "url": "https://example.news/weather",
                "domain": "example.news",
            },
        ]
    }

    captured = {}

    class FakeResponse:
        def read(self):
            return json.dumps(payload).encode()

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        return FakeResponse()

    monkeypatch.setattr("worker.ingest.urlopen", fake_urlopen)
    monkeypatch.setattr(
        "worker.ingest.resolve_location",
        lambda title, content: {
            "lat": None,
            "lng": None,
            "location_text": "",
            "location_method": "unresolved",
            "location_confidence": 0.0,
            "location_precision_meters": None,
            "geocoder_provider": "",
            "geocoder_query": "",
            "geocoder_raw": "",
        },
    )

    threads = fetch_gdelt_threads()

    assert "timespan=" in captured["url"]
    assert len(threads) == 1
    thread = threads[0]
    assert thread["thread_id"].startswith("gdelt-")
    assert thread["subreddit"] == "news:gdelt:example.news"
    assert thread["url"] == "https://example.news/potholes-ring-road"
    assert thread["published_at"].strftime("%Y%m%dT%H%M%S") == seendate[:-1]


def test_fetch_issue_trends_buckets_by_day_and_issue(monkeypatch):
    from app.services import cluster_service

    engine = create_sqlite_test_engine()
    with engine.begin() as conn:
        for day_offset, thread_id, cluster_id, keywords, issue_type in [
            (0, "t-1", "cluster_1", "pothole road", "Road & Traffic"),
            (0, "t-2", "cluster_1", "pothole road", "Road & Traffic"),
            (1, "t-3", "cluster_1", "pothole road", "Road & Traffic"),
            (1, "t-4", "cluster_2", "garbage dump", "Sanitation"),
            (3, "t-5", "cluster_3", "streetlight dark", None),  # falls back to inference
        ]:
            stamp = (cluster_service.datetime.now(cluster_service.timezone.utc) - cluster_service.timedelta(days=day_offset)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                sa.text("""
                    INSERT INTO daily_ingest (thread_id, subreddit, title, content, flair, upvotes, published_at)
                    VALUES (:tid, 'delhi', 'title', 'content', '', 0, :pub)
                """),
                {"tid": thread_id, "pub": stamp},
            )
            conn.execute(
                sa.text("""
                    INSERT OR IGNORE INTO cluster_results (cluster_id, cluster_label, centroid_lat, centroid_lng, size, keywords)
                    VALUES (:cid, 0, 28.6, 77.2, 1, :kw)
                """),
                {"cid": cluster_id, "kw": keywords},
            )
            conn.execute(
                sa.text("INSERT INTO thread_cluster_map (thread_id, cluster_id) VALUES (:tid, :cid)"),
                {"tid": thread_id, "cid": cluster_id},
            )
            if issue_type is not None:
                conn.execute(
                    sa.text("""
                        INSERT OR IGNORE INTO llm_proposals (proposal_id, cluster_id, issue_type, urgency, summary,
                                                   recommendations, funding_sources, estimated_budget,
                                                   communication_plan, responsible_agencies, impact_rationale)
                        VALUES (:pid, :cid, :issue, 'medium', 's', '[]', '[]', '₹1', '[]', '[]', 'r')
                    """),
                    {"pid": "p-" + cluster_id, "cid": cluster_id, "issue": issue_type},
                )

    monkeypatch.setattr(cluster_service, "engine", engine)
    monkeypatch.setattr(cluster_service, "database_available", lambda: True)

    result = cluster_service.fetch_issue_trends(days=5)

    assert len(result["days"]) == 5
    series_by_issue = {s["issue_type"]: s for s in result["series"]}
    assert series_by_issue["Road & Traffic"]["total"] == 3
    assert series_by_issue["Road & Traffic"]["counts"][-1] == 2  # today: two complaints
    assert series_by_issue["Sanitation"]["total"] == 1
    # No LLM proposal for cluster_3: issue type inferred from its keywords.
    assert series_by_issue["Public Lighting"]["total"] == 1
    assert result["total_recent"] == 5


def test_backfill_geocodes_unlocated_threads_and_updates_db(monkeypatch):
    from worker import backfill as backfill_mod

    engine = create_sqlite_test_engine()
    with engine.begin() as conn:
        for tid, title in [
            ("old-1", "Sewer overflow near Lajpat Nagar market"),
            ("old-2", "Random post with no location at all"),
        ]:
            conn.execute(
                sa.text("""
                    INSERT INTO daily_ingest (thread_id, subreddit, title, content, flair, upvotes)
                    VALUES (:tid, 'delhi', :title, 'body', '', 0)
                """),
                {"tid": tid, "title": title},
            )
        # old-3 is already located; must not be selected.
        conn.execute(
            sa.text("""
                INSERT INTO daily_ingest (thread_id, subreddit, title, content, flair, upvotes)
                VALUES ('old-3', 'delhi', 'Pothole in Saket', 'body', '', 0)
            """)
        )
        conn.execute(
            sa.text("""
                INSERT INTO thread_geo (thread_id, lat, lng, source) VALUES ('old-3', 28.52, 77.20, 'delhi')
            """)
        )

    monkeypatch.setattr(backfill_mod.db, "engine", engine)

    def fake_resolve(title, content):
        if "Lajpat Nagar" in title:
            return {
                "lat": 28.5678, "lng": 77.2432, "location_text": "Lajpat Nagar",
                "location_method": "ai_extracted_geocoder", "location_confidence": 0.8,
                "location_precision_meters": 900, "geocoder_provider": "nominatim",
                "geocoder_query": "Lajpat Nagar, Delhi, India", "geocoder_raw": "{}",
            }
        return {
            "lat": None, "lng": None, "location_text": "", "location_method": "ai_place_extraction",
            "location_confidence": 0.0, "location_precision_meters": None,
            "geocoder_provider": "", "geocoder_query": "", "geocoder_raw": "",
        }

    monkeypatch.setattr(backfill_mod, "resolve_location", fake_resolve)

    stats = backfill_mod.run_backfill(limit=10, recluster=False)

    assert stats == {"candidates": 2, "resolved": 1, "failed": 1}

    with engine.connect() as conn:
        coords = conn.execute(
            sa.text("SELECT coordinates FROM daily_ingest WHERE thread_id = 'old-1'")
        ).scalar_one()
        geo_row = conn.execute(
            sa.text("SELECT lat, lng, location_text FROM thread_geo WHERE thread_id = 'old-1'")
        ).fetchone()
        # old-2 (still unresolved) got a thread_geo row with NULL coords, blocking repeat churn.
        unresolved_row = conn.execute(
            sa.text("SELECT lat, lng FROM thread_geo WHERE thread_id = 'old-2'")
        ).fetchone()
        # old-3 was untouched.
        untouched = conn.execute(
            sa.text("SELECT COUNT(*) FROM thread_geo WHERE thread_id = 'old-3' AND lat = 28.52")
        ).scalar_one()

    assert geo_row[0] == 28.5678 and geo_row[2] == "Lajpat Nagar"
    assert unresolved_row[0] is None
    assert untouched == 1

    import json as _json
    assert _json.loads(coords)["lat"] == 28.5678


def test_slug_location_candidates_extracts_gazetteer_and_phrases():
    from worker.backfill import _slug_location_candidates

    hits = _slug_location_candidates("https://example.com/news/delhi/water-crisis-in-lajpat-nagar-market/article")
    assert "Lajpat Nagar" in hits

    phrase_hits = _slug_location_candidates("https://example.com/cities/delhi-news/potholes-terrorise-mayur-vihar-residents")
    assert any("Mayur Vihar" in h for h in phrase_hits)

    assert _slug_location_candidates("") == []
    assert _slug_location_candidates("not-a-url") == []


def test_resolve_with_hints_falls_back_to_slug(monkeypatch):
    from worker import backfill as backfill_mod

    def no_location(title, content):
        return {
            "lat": None, "lng": None, "location_text": "", "location_method": "ai_place_extraction",
            "location_confidence": 0.0, "location_precision_meters": None,
            "geocoder_provider": "", "geocoder_query": "", "geocoder_raw": "",
        }

    monkeypatch.setattr(backfill_mod, "resolve_location", no_location)
    monkeypatch.setattr(backfill_mod, "geocode_text", lambda q: {"lat": 28.5678, "lng": 77.2432, "raw": {}})

    geo = backfill_mod.resolve_with_hints({
        "thread_id": "t", "title": "Water supply hit in several areas",
        "content": "short", "url": "https://example.com/delhi/water-crisis-lajpat-nagar-after-pipeline-burst",
    })

    assert geo["lat"] == 28.5678
    assert geo["location_method"] == "backfill_url_slug"
    assert geo["location_text"] == "Lajpat Nagar"


def test_prune_unlocated_threads_deletes_only_matching_rows(monkeypatch):
    from worker import backfill as backfill_mod

    engine = create_sqlite_test_engine()
    with engine.begin() as conn:
        # Prunable: old, unlocated, news, never mapped to a geocoded cluster.
        conn.execute(sa.text("""
            INSERT INTO daily_ingest (thread_id, subreddit, title, content, published_at)
            VALUES ('stale-news', 'news:toi-delhi', 't', 'c', datetime('now', '-60 days'))
        """))
        # Protected: recent.
        conn.execute(sa.text("""
            INSERT INTO daily_ingest (thread_id, subreddit, title, content, published_at)
            VALUES ('recent-news', 'news:toi-delhi', 't', 'c', datetime('now', '-2 days'))
        """))
        # Protected: located (has thread_geo coords).
        conn.execute(sa.text("""
            INSERT INTO daily_ingest (thread_id, subreddit, title, content, published_at)
            VALUES ('located-news', 'news:toi-delhi', 't', 'c', datetime('now', '-60 days'))
        """))
        conn.execute(sa.text("INSERT INTO thread_geo (thread_id, lat, lng) VALUES ('located-news', 28.6, 77.2)"))
        # Protected: reddit source.
        conn.execute(sa.text("""
            INSERT INTO daily_ingest (thread_id, subreddit, title, content, published_at)
            VALUES ('old-reddit', 'delhi', 't', 'c', datetime('now', '-60 days'))
        """))
        # Protected: mapped to a geocoded cluster.
        conn.execute(sa.text("""
            INSERT INTO daily_ingest (thread_id, subreddit, title, content, published_at)
            VALUES ('mapped-news', 'news:toi-delhi', 't', 'c', datetime('now', '-60 days'))
        """))
        # Prunable despite a cluster mapping: the mapped cluster is unlocated.
        conn.execute(sa.text("""
            INSERT INTO cluster_results (cluster_id, cluster_label, centroid_lat, centroid_lng, size, keywords)
            VALUES ('cluster_noloc', 1, NULL, NULL, 2, 'kw')
        """))
        conn.execute(sa.text("INSERT INTO thread_cluster_map (thread_id, cluster_id) VALUES ('stale-news', 'cluster_noloc')"))
        conn.execute(sa.text("""
            INSERT INTO cluster_results (cluster_id, cluster_label, centroid_lat, centroid_lng, size, keywords)
            VALUES ('cluster_geo', 0, 28.6, 77.2, 2, 'kw')
        """))
        conn.execute(sa.text("INSERT INTO thread_cluster_map (thread_id, cluster_id) VALUES ('mapped-news', 'cluster_geo')"))

    monkeypatch.setattr(backfill_mod.db, "engine", engine)

    stats = backfill_mod.prune_unlocated_threads(older_than_days=45, limit=100)

    assert stats["candidates"] == 1
    assert stats["deleted"] == 1
    with engine.connect() as conn:
        remaining = {r[0] for r in conn.execute(sa.text("SELECT thread_id FROM daily_ingest")).fetchall()}
    assert remaining == {"recent-news", "located-news", "old-reddit", "mapped-news"}


def test_create_tables_adds_new_daily_ingest_columns_to_existing_schema(monkeypatch):
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(sa.text("""
            CREATE TABLE daily_ingest (
                thread_id TEXT PRIMARY KEY,
                subreddit TEXT,
                title TEXT,
                content TEXT,
                flair TEXT,
                upvotes INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """))

    import app.core.database as database

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database.settings, "database_url", "sqlite://:memory:")

    database.create_tables()

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(daily_ingest)"))}

    assert {"coordinates", "url", "published_at"}.issubset(columns)


def test_create_tables_adds_llm_proposal_centroid_columns_to_existing_schema(monkeypatch):
    """Regression: production llm_proposals predates centroid columns, which made
    every LLM proposal storage fail with UndefinedColumn (heuristic_fallback only)."""
    engine = sa.create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(sa.text("""
            CREATE TABLE llm_proposals (
                proposal_id TEXT PRIMARY KEY,
                cluster_id  TEXT UNIQUE,
                issue_type  TEXT,
                urgency     TEXT,
                summary     TEXT,
                recommendations TEXT,
                funding_sources TEXT,
                estimated_budget TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """))

    import app.core.database as database

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database.settings, "database_url", "sqlite://:memory:")

    database.create_tables()

    with engine.connect() as conn:
        columns = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(llm_proposals)"))}

    assert {"centroid_lat", "centroid_lng"}.issubset(columns)


def test_call_groq_rejects_non_object_json(monkeypatch):
    from app.services import proposal_generator as pg

    class FakeResp:
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "[1, 2, 3]"}}]}).encode()

    monkeypatch.setattr(pg, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(pg, "urlopen", lambda req, timeout=90: FakeResp())

    # Regression: a list-shaped response used to crash the whole pipeline.
    assert pg.call_groq("sys", "user") is None
    assert pg.generate_proposal_for_cluster("c1", "kw", 2, None, None, []) is None


def test_call_groq_retries_on_429_then_succeeds(monkeypatch):
    from email.message import Message
    from urllib.error import HTTPError
    from app.services import proposal_generator as pg

    calls = {"n": 0}
    sleeps: list[float] = []

    class FakeResp:
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "{\"summary\": \"ok\"}"}}]}).encode()

    def fake_urlopen(req, timeout=90):
        calls["n"] += 1
        if calls["n"] < 3:
            raise HTTPError("https://api.groq.com", 429, "Too Many Requests", Message(), None)
        return FakeResp()

    monkeypatch.setattr(pg, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(pg, "urlopen", fake_urlopen)
    monkeypatch.setattr(pg.time, "sleep", lambda s: sleeps.append(s))

    result = pg.call_groq("sys", "user")

    assert result == {"summary": "ok"}
    assert calls["n"] == 3
    assert len(sleeps) == 2


def test_decode_json_column_tolerates_jsonb_lists():
    from app.services.proposal_generator import _decode_json_column

    # Regression: production Neon stores these columns as JSONB, so psycopg
    # returns Python lists — json.loads(list) crashed every fetch.
    assert _decode_json_column(["a", "b"]) == ["a", "b"]
    assert _decode_json_column('["a", "b"]') == ["a", "b"]
    assert _decode_json_column(None) == []
    assert _decode_json_column("") == []
    assert _decode_json_column("not json") == []
    assert _decode_json_column("{\"obj\": true}") == []


def test_geocoding_model_decoupled_from_groq_model(monkeypatch):
    import importlib
    from worker import geocoding as g

    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
    monkeypatch.delenv("GEO_LLM_MODEL", raising=False)
    reloaded = importlib.reload(g)
    try:
        assert reloaded.GEO_LLM_MODEL != "openai/gpt-oss-120b"
    finally:
        monkeypatch.undo()
        importlib.reload(g)


def test_fetch_sources_for_cluster_orders_by_recency(monkeypatch):
    from app.services import cluster_service

    engine = create_sqlite_test_engine()
    with engine.begin() as conn:
        conn.execute(sa.text("""
            INSERT INTO cluster_results (cluster_id, cluster_label, centroid_lat, centroid_lng, size, keywords)
            VALUES ('cluster_recent', 0, 28.6, 77.2, 2, 'kw')
        """))
        conn.execute(sa.text("""
            INSERT INTO daily_ingest (thread_id, subreddit, title, content, published_at)
            VALUES ('old-thread', 'news:toi-delhi', 'Old story', 'c', datetime('now', '-60 days'))
        """))
        conn.execute(sa.text("""
            INSERT INTO daily_ingest (thread_id, subreddit, title, content, published_at)
            VALUES ('new-thread', 'news:toi-delhi', 'Fresh story', 'c', datetime('now', '-1 days'))
        """))
        # Insert the stale mapping first: without an ORDER BY the DB would
        # surface the old row first (insertion order), which is the bug.
        conn.execute(sa.text("INSERT INTO thread_cluster_map (thread_id, cluster_id) VALUES ('old-thread', 'cluster_recent')"))
        conn.execute(sa.text("INSERT INTO thread_cluster_map (thread_id, cluster_id) VALUES ('new-thread', 'cluster_recent')"))

    monkeypatch.setattr(cluster_service, "engine", engine)

    sources = cluster_service.fetch_sources_for_cluster("cluster_recent", limit=8)

    assert [s["id"] for s in sources] == ["new-thread", "old-thread"]
    assert sources[0]["published_at"] is not None
