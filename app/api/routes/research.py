"""
Research pipeline endpoints — agentic SSE stream and report download.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
import sqlalchemy as sa

from app.core.database import engine, init_db_sync

router = APIRouter()


@router.get("/research/{cluster_id}")
async def research_cluster_stream(cluster_id: str):
    """Stream research pipeline steps as SSE."""
    init_db_sync()

    async def event_stream():
        from research import run_research
        for step in run_research(cluster_id, engine):
            yield f"data: {json.dumps(step)}\n\n"
            await asyncio.sleep(0.1)
        yield 'data: {"step": "done"}\n\n'

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/agent-runs/{cluster_id}")
async def get_agent_runs(cluster_id: str, limit: int = 5):
    """Return recent persisted agent runs and tool traces for a cluster."""
    init_db_sync()
    try:
        with engine.connect() as conn:
            runs = conn.execute(
                sa.text("""
                    SELECT run_id, status, started_at, finished_at
                    FROM agent_runs
                    WHERE cluster_id = :cid
                    ORDER BY started_at DESC
                    LIMIT :lim
                """),
                {"cid": cluster_id, "lim": limit},
            ).fetchall()
            run_ids = [r[0] for r in runs]
            if not run_ids:
                return {"runs": []}
            steps = conn.execute(
                sa.text("""
                    SELECT run_id, step_name, tool_name, status, input_json, output_json, created_at
                    FROM agent_steps
                    WHERE run_id IN :run_ids
                    ORDER BY created_at ASC
                """).bindparams(sa.bindparam("run_ids", expanding=True)),
                {"run_ids": run_ids},
            ).fetchall()
        steps_by_run: dict[str, list[dict]] = {}
        for step in steps:
            steps_by_run.setdefault(step[0], []).append({
                "step_name": step[1],
                "tool_name": step[2],
                "status": step[3],
                "input": json.loads(step[4]) if step[4] else {},
                "output": json.loads(step[5]) if step[5] else {},
                "created_at": step[6] if step[6] else None,
            })
        return {
            "runs": [
                {
                    "run_id": run[0],
                    "status": run[1],
                    "started_at": run[2] if run[2] else None,
                    "finished_at": run[3] if run[3] else None,
                    "steps": steps_by_run.get(run[0], []),
                }
                for run in runs
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/research/{cluster_id}/download/{doc_id}")
async def download_research_report(cluster_id: str, doc_id: str):
    """Download the generated research report as markdown."""
    init_db_sync()
    try:
        from research import run_research
        doc = None
        for step in run_research(cluster_id, engine):
            if step.get("step") == "document" and step["status"] == "done":
                doc = step["output"]
                break
        if not doc:
            raise HTTPException(status_code=404, detail="No document found")
        return Response(
            content=doc,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=conflux-report-{cluster_id}.md"},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
