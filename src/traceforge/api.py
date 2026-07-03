"""FastAPI serving layer.

Loads the bronze dataset once at startup, builds the retrieval index, and exposes the
compliance and Q&A surface. The `/ask` endpoint takes the caller's clearance and enforces it
in retrieval. Run: `uvicorn traceforge.api:app --reload`.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import ingest, quality, trace
from .models import Classification
from .pipeline import compliance
from .rag import Rag

BRONZE = os.getenv("TRACEFORGE_BRONZE", "data/bronze/trus")

app = FastAPI(title="TraceForge", version="0.1.0",
              description="Requirements traceability & compliance copilot")

_state: dict = {}


def _get() -> dict:
    """Lazily load the dataset + index on first request (works under uvicorn and tests)."""
    if not _state:
        reqs, tests, design = ingest.load_bronze(BRONZE)
        quality.annotate(reqs)
        _state.update(reqs=reqs, tests=tests, design=design, rag=Rag(BRONZE))
    return _state


class AskRequest(BaseModel):
    question: str
    clearance: str = "OPEN"


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "retrieval_backend": _get()["rag"].index.backend}


@app.post("/ask")
def ask(req: AskRequest) -> dict:
    try:
        clearance = Classification.parse(req.clearance)
    except KeyError:
        raise HTTPException(400, f"invalid clearance: {req.clearance}")
    res = _get()["rag"].answer(req.question, clearance)
    return {
        "answer": res.answer,
        "refused": res.refused,
        "citations": res.citations,
        "contexts": res.contexts,
        "clearance": clearance.name,
        "backend": res.backend,
    }


@app.get("/report")
def report() -> dict:
    return compliance(BRONZE).model_dump()


@app.get("/requirements")
def requirements() -> list[dict]:
    return [r.model_dump() for r in _get()["reqs"]]


@app.get("/quality")
def quality_flags() -> dict:
    reqs = _get()["reqs"]
    return {r.requirement_id: r.quality_flags for r in reqs if r.quality_flags}


@app.get("/orphans")
def orphans() -> dict:
    st = _get()
    reqs, tests = st["reqs"], st["tests"]
    return {
        "orphan_requirements": trace.orphan_requirements(reqs, tests),
        "orphan_tests": trace.orphan_tests(reqs, tests),
    }


@app.get("/requirements/{requirement_id}/trace")
def trace_requirement(requirement_id: str) -> dict:
    st = _get()
    reqs, tests, design = st["reqs"], st["tests"], st["design"]
    if not any(r.requirement_id == requirement_id for r in reqs):
        raise HTTPException(404, f"unknown requirement: {requirement_id}")
    return {
        "requirement_id": requirement_id,
        "verified_by": [t.test_id for t in tests if requirement_id in t.covers],
        "satisfied_by": [d.design_id for d in design if requirement_id in d.satisfies],
    }
