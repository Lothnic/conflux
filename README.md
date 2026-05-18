# Conflux

> "The flowing together" — where the scattered streams of citizen feedback merge into structured, actionable urban intelligence.

**Author:** Lothnic

## What is Conflux?

Conflux is a civic-tech AI platform that transforms raw, multilingual citizen complaints from social media and public portals into structured, geospatially-aware infrastructure proposals.

**The Pipeline:**
1. **Ingest:** Scrape Reddit, Nextdoor, and government feedback.
2. **Align:** Use multilingual embedding models to map complaints into a shared semantic space.
3. **Cluster:** HDBSCAN groups complaints by geospatial location and semantic meaning.
4. **Analyze:** Local LLM agents generate policy proposals, funding sources, and maintenance plans for each cluster.
5. **Visualize:** A Next.js + Folium dashboard maps "hotspots" of urban decay and infrastructure failure.

## 🛠️ Tech Stack

* **Backend:** FastAPI + Uvicorn
* **ML:** sentence-transformers (xlm-R), UMAP, HDBSCAN, Ollama (local LLM)
* **Frontend:** Next.js 14 (App Router) + Tailwind CSS
* **Data:** pyproject.toml managed with `uv`

## 🚀 Quick Starts

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
