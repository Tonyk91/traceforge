"""FastAPI serving layer.

Loads the bronze dataset once at startup, builds the retrieval index, and exposes the
compliance and Q&A surface. The `/ask` endpoint takes the caller's clearance and enforces it
in retrieval. Run: `uvicorn traceforge.api:app --reload`.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ingest, quality, trace
from .models import Classification
from .pipeline import compliance
from .rag import Rag

BRONZE = os.getenv("TRACEFORGE_BRONZE", "data/bronze/trus")
STATIC = Path(__file__).parent / "static"

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


@app.get("/matrix")
def matrix(clearance: str = "OPEN") -> dict:
    """Traceability matrix filtered to the caller's clearance.

    Need-to-know applies to the compliance view too: requirements (and the tests/design that
    trace to them) above the caller's clearance are withheld, not merely hidden client-side.
    """
    try:
        clr = Classification.parse(clearance)
    except KeyError:
        raise HTTPException(400, f"invalid clearance: {clearance}")
    st = _get()
    reqs, tests, design = st["reqs"], st["tests"], st["design"]
    verified = trace.verified_requirements(reqs, tests)
    rows = []
    for r in (rq for rq in reqs if rq.classification <= clr):
        rows.append({
            "requirement_id": r.requirement_id,
            "section": r.section,
            "classification": r.classification.name,
            "verification_method": r.verification_method,
            "quality_flags": r.quality_flags,
            "verified_by": [t.test_id for t in tests
                            if r.requirement_id in t.covers and t.classification <= clr],
            "satisfied_by": [d.design_id for d in design
                             if r.requirement_id in d.satisfies and d.classification <= clr],
            "verified": r.requirement_id in verified,
        })
    return {
        "clearance": clr.name,
        "total_requirements": len(reqs),
        "visible_requirements": len(rows),
        "withheld": len(reqs) - len(rows),
        "rows": rows,
    }


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse("/ui/")


if STATIC.is_dir():
    app.mount("/ui", StaticFiles(directory=str(STATIC), html=True), name="ui")
