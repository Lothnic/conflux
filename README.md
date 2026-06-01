# Conflux

> "The flowing together" - where the scattered streams of citizen feedback merge into structured, actionable urban intelligence.

**Author:** Lothnic

## What is Conflux?

Conflux is a civic-tech AI platform that transforms raw, multilingual citizen complaints from social media and public portals into structured, geospatially-aware infrastructure proposals.

**The Pipeline:**
1. **Ingest:** Pull civic reports from public, ToS-clean Indian-city sources — civic **news RSS** feeds, **Google News RSS** queries for infrastructure complaints, and optionally India's official **data.gov.in** open-data API. A legacy Reddit adapter exists, but is disabled by default because anonymous Reddit access is unreliable.
2. **Align:** Use multilingual embedding models to map complaints into a shared semantic space.
3. **Cluster:** HDBSCAN groups complaints by geospatial location and semantic meaning.
4. **Analyze:** LLM agents generate per-cluster proposals — summary, recommendations, **funding sources**, **responsible agencies**, a sequenced **communication & outreach plan**, an **impact/urgency rationale**, and an INR budget.
5. **Visualize:** A Next.js + Leaflet dashboard maps "hotspots" of urban decay, with a deep-dive research engine (satellite context, nearby POIs, policy analysis) that exports a downloadable report.

## Tech Stack

* **Backend:** FastAPI + Uvicorn
* **ML:** sentence-transformers, UMAP, HDBSCAN, Groq proposal generation
* **Frontend:** Next.js 16 (App Router) + Tailwind CSS
* **Data:** pyproject.toml managed with `uv`
* **Worker:** GitHub Actions scheduled ingestion

## Quick Start

```bash
# 1. Install Python deps
uv sync

# 2. Start the backend
uvicorn main:app --reload --port 8000

# 3. Start the frontend (in a separate terminal)
cd frontend
npm run dev
```

* **Backend API:** http://localhost:8000
* **Frontend Dashboard:** http://localhost:3000
