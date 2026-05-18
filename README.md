# New Builds Delhi

**Repo Owner:** Shweta  
**Team Members:** Shweta, Mayank, Rajan, Aarav, Nisha  

Civic-tech AI platform for Delhi — transforms citizen complaints from social media and public sources into structured, geospatially-aware infrastructure proposals.

## Tech Stack

- **Backend:** FastAPI + Uvicorn
- **ML:** sentence-transformers (xlm-R), UMAP, HDBSCAN, Ollama (local LLM)
- **Frontend:** Next.js 14 (App Router) + Tailwind CSS
- **Data:** pyproject.toml managed with `uv`

## Quick Start

```bash
# 1. Install Python deps
uv sync

# 2. Activate venv
source .venv/bin/activate

# 3. Start backend
uvicorn main:app --reload --port 8000

# 4. Start frontend (in another terminal)
cd frontend
npm run dev
```

- Backend: http://localhost:8000
- Frontend: http://localhost:3000
