# Conflux Infrastructure & Data Design

## 1. System Architecture

The project is split into two distinct environments to respect Vercel's stateless constraints and GPU requirements for ML.

- **Vercel (Frontend + API):**
  - Next.js dashboard.
  - Serverless routes for lightweight queries.
  - No background jobs, no GPU, no `uvicorn`.

- **External Worker (Ingestion + ML):**
  - Runs on **GitHub Actions** (free tier, every 4 hours).
  - Handles `praw`/RSS fetching, `torch` clustering (`umap`/`hdbscan`), and `ollama`.
  - Communicates with the shared Database.

## 2. Reddit Ingestion Strategy

- **Source:** Public RSS feeds (`/r/{subreddit}/new/.json`) to avoid `praw` credentials/limits.
- **Frequency:** Every 4 hours via **Render Cron Job**.
- **Deduplication:** All records are stored by `thread_id` (Reddit provides these), so no daily overlap.
- **Worker:** `worker/ingest_and_cluster.py` runs on Render's free tier.

## 3. Database Schema

Targeting Neon (Postgres) or Turso (SQLite). The schema relies on standard SQL + JSON for flexibility.

### Table: `daily_ingest`
Raw data storage for every fetched thread.

| Column | Type | Notes |
| :--- | :--- | :--- |
| `thread_id` | `VARCHAR(32)` | Primary Key, Reddit ID |
| `subreddit` | `VARCHAR` | Source (e.g., r/delhi) |
| `title` | `TEXT` | |
| `content` | `TEXT` | Body text |
| `flair` | `VARCHAR` | |
| `upvotes` | `INT` | |
| `coordinates` | `JSONB` | `{"lat": 28.6, "lng": 77.2}` |
| `timestamp` | `TIMESTAMP` | `published_at` |
| `created_at` | `TIMESTAMP` | Ingestion timestamp |

### Table: `cluster_results`
Output of the ML pipeline.

| Column | Type | Notes |
| :--- | :--- | :--- |
| `cluster_id` | `VARCHAR` | Hash or auto-increment |
| `centroid_lat` | `FLOAT` | |
| `centroid_lng` | `FLOAT` | |
| `size` | `INT` | Number of threads in cluster |
| `keywords` | `TEXT` | |
| `created_at` | `TIMESTAMP` | |

### Table: `llm_proposals`
AI-generated solutions for each cluster.

| Column | Type | Notes |
| :--- | :--- | :--- |
| `proposal_id` | `VARCHAR` | Primary Key |
| `cluster_id` | `VARCHAR` | FK to cluster_results |
| `summary` | `TEXT` | |
| `budget_estimate` | `VARCHAR` | |
| `priority_score` | `INT` | |
| `status` | `VARCHAR` | `draft`, `approved` |
| `created_at` | `TIMESTAMP` | |

## 4. Data Flow

1. **Worker** fetches RSS -> checks `daily_ingest` for `thread_id`.
2. **Worker** saves new rows to `daily_ingest`.
3. **Worker** runs HDBSCAN + LLM -> populates `cluster_results` and `llm_proposals`.
4. **Vercel** reads from `cluster_results` and `llm_proposals` via API.

## 5. Tech Stack Summary

- **Frontend:** Next.js 14, Tailwind, Vercel.
- **Worker:** Python (uvicorn), PRAW/RSS, Torch, Scipy, Umap/HDScan.
- **Database:** Neon (Postgres) or Turso (SQLite).
- **Orchestration:** GitHub Actions (Cron) or systemd (VPS).
