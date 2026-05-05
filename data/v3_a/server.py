"""FastAPI sidecar exposing data.v3_a.api over HTTP.

Spec §6.4 of docs/superpowers/specs/2026-05-05-trafficure-v3a-integration-design.md.

Run:
    uvicorn data.v3_a.server:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from data.v3_a.api import get_run, list_runs, submit_run
from data.v3_a.errors import HardError
from data.v3_a.progress import RunStatus


log = logging.getLogger("data.v3_a.server")

app = FastAPI(title="Corridor Diagnostics v3-A sidecar", version="3.a.0")


class RunRequest(BaseModel):
    corridor_id: str
    anchor_ts: str
    mode: str = "today_as_of_T"


@app.post("/v3a/run")
def run(req: RunRequest):
    if req.mode not in ("today_as_of_T", "retrospective"):
        raise HTTPException(status_code=400, detail={"code": "HARD_ERR_BAD_CONFIG",
                                                     "message": f"unsupported mode {req.mode!r}"})
    try:
        run_id = submit_run(req.corridor_id, req.anchor_ts, mode=req.mode)
    except HardError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    return {"run_id": run_id, "status": "queued"}


@app.get("/v3a/run/{run_id}")
def get(run_id: str):
    try:
        rec = get_run(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "run_id": run_id})
    return rec.to_dict()


@app.get("/v3a/runs")
def list_(corridor_id: Optional[str] = None, status: Optional[str] = None):
    s = RunStatus(status) if status else None
    return [r.to_dict() for r in list_runs(corridor_id=corridor_id, status=s)]


@app.get("/v3a/health")
def health():
    return {"status": "ok", "version": "3.a.0"}
