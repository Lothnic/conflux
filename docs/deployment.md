# Deployment

Conflux is a split deployment:

- `frontend/` is the public Next.js dashboard and is ready for Vercel.
- `main.py` is the FastAPI backend. Deploy it as a separate Python web service, or use Vercel Services if your Vercel account has private beta access.
- `worker/` runs ingestion, geocoding, embeddings, and clustering. Keep it out of the request path and run it from GitHub Actions or another scheduled worker.

This split keeps the public runtime small. The worker depends on heavy ML packages, while the web API mostly reads prepared data and calls LLM APIs on demand.

## Frontend on Vercel

Create a Vercel project with `frontend` as the root directory.

Required settings:

- Framework preset: `Next.js`
- Install command: `npm ci`
- Build command: `npm run build`
- Environment variables:
  - `API_URL=https://<your-api-host>`
  - `NEXT_PUBLIC_API_URL=https://<your-api-host>`

The frontend calls `/api/*`; `frontend/next.config.ts` rewrites those requests to `API_URL`.

## FastAPI Backend

For a free or low-cost deployment, use a Python ASGI host with persistent environment variables and a Postgres database. Set:

```bash
DATABASE_URL=postgresql://...
GROQ_API_KEY=...
GROQ_MODEL=llama-3.3-70b-versatile
CORS_ALLOWED_ORIGINS=https://<your-vercel-app>.vercel.app
```

Use this start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

For a public demo without a database, set:

```bash
CONFLUX_DEMO=1
CORS_ALLOWED_ORIGINS=https://<your-vercel-app>.vercel.app
```

Demo mode serves the bundled sample data and skips database initialization during FastAPI startup.


## FastAPI Backend on Render

This repo includes a Render-ready API deployment:

- `render.yaml` defines the Render web service.
- `requirements-render.txt` installs only lightweight API dependencies.
- `CONFLUX_DEMO=1` is the default in `render.yaml` so the API can deploy without a production database.

Manual Render settings if you do not use the blueprint:

```text
Service type: Web Service
Runtime: Python
Plan: Free
Build command: pip install -r requirements-render.txt
Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
Health check path: /health
```

Set these environment variables for a demo deploy:

```bash
CONFLUX_DEMO=1
CORS_ALLOWED_ORIGINS=https://<your-vercel-app>.vercel.app
GROQ_API_KEY=<optional-for-LLM-features>
```

Set these for a real database-backed deploy:

```bash
CONFLUX_DEMO=0
DATABASE_URL=postgresql://...
CORS_ALLOWED_ORIGINS=https://<your-vercel-app>.vercel.app
GROQ_API_KEY=...
```

Use an external Postgres database for production data. Do not rely on Render's local filesystem for SQLite persistence on the free web service.

## Worker

The scheduled GitHub Action in `.github/workflows/ingest.yml` should point at the same production `DATABASE_URL` as the backend. Store secrets in GitHub Actions:

- `DATABASE_URL`
- `GROQ_API_KEY`
- `GEO_LLM_API_KEY` if different from Groq

The worker should not run inside Vercel serverless functions because embedding and clustering dependencies are large and slow for request/response execution.

## Vercel Services Option

Vercel Services can mount a Next.js frontend and FastAPI backend in one Vercel project, but as of March 11, 2026 Vercel lists Services as private beta. If your account has access, add a root `vercel.json` like:

```json
{
  "experimentalServices": {
    "web": {
      "entrypoint": "frontend",
      "routePrefix": "/",
      "framework": "nextjs"
    },
    "api": {
      "entrypoint": "main.py",
      "routePrefix": "/api",
      "framework": "fastapi",
      "excludeFiles": "{tests/**,worker/**,graphify-out/**,.venv/**,frontend/**}"
    }
  }
}
```

Only use this after moving heavy worker-only dependencies out of the API install set; Python functions have a 500 MB uncompressed bundle limit on Vercel.
