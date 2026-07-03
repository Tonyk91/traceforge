"""MCP server — exposes the traceability & compliance surface as tools for LLM agents.

Saab's stack calls for MCP: this makes TraceForge a first-class tool provider that a Copilot,
Claude Desktop, or an agent orchestrator can call directly. Every retrieval-backed tool takes
the caller's ``clearance`` and enforces it in the retriever, so an agent wired to this server
inherits the same need-to-know access control the API and CLI enforce — the model can never
surface a requirement the caller is not cleared to see.

Run as a stdio server:  ``python -m traceforge.mcp_server``
Register in a client (e.g. Claude Desktop) by pointing it at that command; see
``docs/mcp.md`` for a ready-to-paste config and the ``mcp_client_demo.py`` smoke test.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from . import ingest, quality, trace
from .models import Classification
from .pipeline import compliance
from .rag import Rag

BRONZE = os.getenv("TRACEFORGE_BRONZE", "data/bronze/trus")

mcp = FastMCP("traceforge")

_state: dict = {}


def _get() -> dict:
    """Load the dataset + retrieval index once, on first tool call."""
    if not _state:
        reqs, tests, design = ingest.load_bronze(BRONZE)
        quality.annotate(reqs)
        _state.update(reqs=reqs, tests=tests, design=design, rag=Rag(BRONZE))
    return _state


def _clearance(value: str) -> Classification:
    try:
        return Classification.parse(value)
    except KeyError as exc:  # surfaced to the agent as a tool error
        raise ValueError(f"invalid clearance {value!r}; use OPEN, RESTRICTED, or SECRET") from exc


@mcp.tool()
def search_requirements(query: str, clearance: str = "OPEN") -> dict:
    """Answer a question about the requirements, grounded in retrieved evidence.

    Enforces the caller's ``clearance`` in retrieval and refuses when no accessible requirement
    grounds the question. Returns the answer, cited requirement IDs, and the retrieved contexts.

    Args:
        query: A natural-language question about the system requirements.
        clearance: Caller clearance — OPEN, RESTRICTED, or SECRET. Controls what is visible.
    """
    res = _get()["rag"].answer(query, _clearance(clearance))
    return {
        "answer": res.answer,
        "refused": res.refused,
        "citations": res.citations,
        "contexts": res.contexts,
        "clearance": _clearance(clearance).name,
        "backend": res.backend,
    }


@mcp.tool()
def get_traceability(requirement_id: str) -> dict:
    """Return the bidirectional trace for one requirement: verifying tests and satisfying design.

    Args:
        requirement_id: e.g. "SR-004".
    """
    st = _get()
    reqs, tests, design = st["reqs"], st["tests"], st["design"]
    if not any(r.requirement_id == requirement_id for r in reqs):
        raise ValueError(f"unknown requirement: {requirement_id}")
    return {
        "requirement_id": requirement_id,
        "verified_by": [t.test_id for t in tests if requirement_id in t.covers],
        "satisfied_by": [d.design_id for d in design if requirement_id in d.satisfies],
    }


@mcp.tool()
def find_orphans() -> dict:
    """List requirements with no verifying test and tests that reference no requirement."""
    st = _get()
    reqs, tests = st["reqs"], st["tests"]
    return {
        "orphan_requirements": trace.orphan_requirements(reqs, tests),
        "orphan_tests": trace.orphan_tests(reqs, tests),
    }


@mcp.tool()
def check_quality() -> dict:
    """Return deterministic EARS/INCOSE quality flags per requirement plus an overall score."""
    reqs = _get()["reqs"]
    return {
        "quality_score": quality.quality_score(reqs),
        "flags_by_requirement": {
            r.requirement_id: r.quality_flags for r in reqs if r.quality_flags
        },
    }


@mcp.tool()
def compliance_report() -> dict:
    """Full compliance rollup: coverage, orphans, conflicts, duplicates, and quality score."""
    return compliance(BRONZE).model_dump()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
