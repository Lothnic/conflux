# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Conflux ingests citizen complaints (currently Reddit), clusters them by semantic meaning + geolocation, and uses an LLM to generate infrastructure proposals for each cluster. The whole project is scoped to **Delhi, India** — prompts, geocoding defaults, currency (₹/INR), and agency names (MCD/PWD/DJB) are all Delhi-specific. Changing the target city means touching `proposals.py`, `research.py`, and the worker's geocoding defaults, not just config.

## Commands

```bash
# Backend (Python, managed by uv — never use pip directly)
uv sync                                   # install deps incl. dev group
uv run uvicorn main:app --reload --port 8000
uv run python -m pytest                   # all tests (use `python -m` so repo root is importable — `uv run pytest` fails to import the top-level `db` module)
uv run python -m pytest tests/test_core.py::test_priority_and_budget_thresholds  # single test

# Worker (ingest + cluster + generate proposals) — runs standalone, not via the API
uv run worker/ingest_and_cluster.py

# Frontend (from frontend/)
npm run dev      # localhost:3000, proxies /api/* to the backend
npm run build
npm run lint
```

## The two-environment split (read `docs/ARCHITECTURE_AND_DATA_DESIGN.md`)

The codebase is deliberately split because of Vercel's stateless/no-GPU constraints:

- **Backend + Frontend** (`main.py`, `frontend/`) serve read-mostly data to the dashboard.
- **Worker** (`worker/ingest_and_cluster.py`) does all the heavy lifting — Reddit fetch, embeddings, UMAP/HDBSCAN clustering, and Groq proposal generation — and runs **out-of-band on GitHub Actions cron** (`.github/workflows/ingest.yml`, every 4h), *not* inside the API process. The FastAPI `/cluster` endpoint imports `cluster_threads()` from the worker, but the canonical pipeline is the cron job's `main()`.

The two sides communicate **only through the shared database** (and, in demo mode, through JSON files in `data/`).

## Demo-mode / local-artifact fallback (the most important non-obvious behavior)

Almost every read path has a three-tier fallback: **local JSON file → database → empty**. `main.py`'s `fetch_latest_clusters`, `fetch_latest_threads`, and `/threads/geojson` check `data/local_*.json` *before* the DB. The worker's `main()` and `main.py`'s `database_available()` short-circuit to demo behavior when `CONFLUX_DEMO=1` or the DB is unreachable:

- Worker in demo mode calls `build_demo_threads()` / `build_demo_clusters()` and writes `data/local_clusters.json`, `data/local_threads.json`, `data/local_threads_geojson.json` instead of hitting the DB.
- API in demo mode forces `database_available()` to `False`, so it serves those same JSON files.

When debugging "stale" or "wrong" dashboard data, check whether a `data/local_*.json` file exists and is shadowing the DB — it wins.

## Database

- Schema is **raw SQL string constants in `db.py`** (`SQLITE_CREATE_TABLES_SQL` / `POSTGRES_CREATE_TABLES_SQL`), not ORM models — keep both dialects in sync when changing schema. There are no migrations; tables are created idempotently via `CREATE TABLE IF NOT EXISTS` on each request (`create_tables()`).
- **Adding a column to an existing table:** `CREATE TABLE IF NOT EXISTS` is a no-op on a DB that already has the table, so new columns won't appear. Add them to the schema SQL **and** to `_ADDED_COLUMNS` in `db.py` — `_ensure_columns()` (called from `create_tables()`) reconciles them with dialect-aware `ALTER TABLE ADD COLUMN`, each in its own transaction.
- Defaults to SQLite (`data/conflux.db`); set `DATABASE_URL` to a Postgres URL for Neon/production.
- Tests build an in-memory SQLite engine by reusing `db.SQLITE_CREATE_TABLES_SQL` (see `tests/test_core.py`) — so that constant is effectively part of the test contract.
- Core tables: `daily_ingest` (raw threads, PK `thread_id` for dedup), `thread_geo`, `cluster_results`, `thread_cluster_map`, `llm_proposals` (one proposal per cluster — `store_proposal` deletes-then-inserts).

## Worker pipeline (`worker/ingest_and_cluster.py`)

`main()` runs: fetch new threads from **three modular sources** → geocode titles/content with Nominatim → dedup-insert by `thread_id` → **combined text+geo clustering**: multilingual sentence-transformer embeddings (`TEXT_WEIGHT`) concatenated with scaled lat/lng features (`GEO_WEIGHT`), reduced by UMAP, clustered by HDBSCAN → extract keywords → generate a Groq proposal per cluster and store it. Heavily tunable via env vars (`UMAP_*`, `HDBSCAN_*`, `TEXT_WEIGHT`, `GEO_WEIGHT`, `EMBEDDING_MODEL`, etc.).

Ingestion sources, all normalized into the **same thread dict shape** (`thread_id`, `subreddit`, `title`, `content`, `flair`, `upvotes`, `published_at`, `lat`, `lng`, `url`, `source`) so they share the geocode → insert → cluster path. Each filters by `INFRA_KEYWORDS`. The `source` field is stored in `thread_geo.source`; `insert_batches` defaults it to `"reddit"`.
- `fetch_new_threads()` — Reddit public JSON across `TARGET_SUBS` (Delhi NCR + Indian metros).
- `fetch_news_threads()` — civic **news RSS** (stdlib `xml.etree`), `subreddit="news:<source>"`. Gated by `NEWS_INGEST_ENABLED`; feeds via `NEWS_FEEDS` ("name|url,..." ) else `DEFAULT_NEWS_FEEDS`.
- `fetch_opendata_threads()` — official **data.gov.in** OGD API, `subreddit="gov:data.gov.in"`. Skips cleanly unless **both** `DATA_GOV_API_KEY` and `DATA_GOV_RESOURCE_ID` are set (mirrors the Groq graceful-skip).

## LLM integration (`proposals.py`, `research.py`)

- Uses **Groq's OpenAI-compatible chat endpoint via raw `urllib`** — no SDK. Requires `GROQ_API_KEY`; if unset, `proposals.py` returns `None` and the API falls back to heuristic proposals (`infer_issue_type` / `infer_urgency` / `infer_budget` / `proposal_recommendations` / `responsible_agencies` / `proposal_communication_plan` / `impact_rationale` in `main.py`). When editing these, preserve the no-key heuristic fallback path so the demo never shows blank sections.
- `proposals.py` requests strict JSON (`response_format: json_object`); the system prompt enforces INR budgets and Delhi context. **Proposal output fields:** `summary`, `recommendations[]`, `funding_sources[]`, `estimated_budget`, `responsible_agencies[]`, `communication_plan[]` (sequenced outreach steps), `impact_rationale`. The list fields are JSON-serialized in `llm_proposals`; both `/proposals` (stored + heuristic branches) and `POST /proposals/generate/{id}` must stay in sync when adding fields.
- `research.py` powers the `/research/{cluster_id}` **SSE stream** (satellite → POI → policy → markdown document), consumed by `ResearchSidebar.tsx`. Each step yields a `data:` event; the final report pulls the stored proposal's fields into "Why This Urgency", "Responsible Agencies", and "Communication & Outreach Plan" sections; the final step is a downloadable markdown report.

## Frontend (`frontend/`)

- **Next.js 16 + React 19 + Tailwind v4 + Leaflet.** Next 16 has breaking changes vs. older versions — per `frontend/AGENTS.md`, consult `node_modules/next/dist/docs/` before writing Next-specific code rather than relying on prior knowledge.
- No backend URL is hardcoded in components: `frontend/next.config.ts` rewrites `/api/:path*` and `/data/:path*` to `NEXT_PUBLIC_API_URL` (default `http://127.0.0.1:8000`). All client calls go through `src/lib/api.ts` against the relative `/api` base.

## Environment variables

See `.env.example`. Key ones: `DATABASE_URL`, `GROQ_API_KEY`, `GROQ_MODEL`, `SUBREDDIT`, `HOURS_BACK`, `CONFLUX_DEMO` (1 = force local-JSON demo mode). Ingestion: `TARGET_SUBS`, `NEWS_INGEST_ENABLED`, `NEWS_FEEDS`, `DATA_GOV_API_KEY`, `DATA_GOV_RESOURCE_ID`. Frontend: `NEXT_PUBLIC_API_URL`.

> Note: `db.py` calls `load_dotenv(override=True)`, so values in `.env` **override** shell env vars. To point a script/test at a scratch DB, edit `.env` or use an in-memory engine directly (as the tests do) — exporting `DATABASE_URL` inline won't take effect.
