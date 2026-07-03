"""The MCP server must expose every tool and carry the same clearance enforcement.

We assert the five tools are registered, that the deterministic tools reproduce the gold
findings, and — the load-bearing one — that ``search_requirements`` enforces clearance exactly
like the RAG core: an OPEN caller never sees a SECRET requirement an agent asks for.
"""

import asyncio

from traceforge import mcp_server as srv

EXPECTED_TOOLS = {
    "search_requirements", "get_traceability", "find_orphans",
    "check_quality", "compliance_report",
}


def test_all_tools_registered():
    names = {t.name for t in asyncio.run(srv.mcp.list_tools())}
    assert names == EXPECTED_TOOLS


def test_find_orphans_matches_gold():
    assert srv.find_orphans()["orphan_requirements"] == ["SR-007", "SR-021", "SR-023"]


def test_get_traceability_bidirectional():
    tr = srv.get_traceability("SR-011")
    assert "TC-010" in tr["verified_by"]
    assert "DE-04" in tr["satisfied_by"]


def test_compliance_report_shape():
    rep = srv.compliance_report()
    assert rep["total_requirements"] == 24
    assert rep["conflicts"] == [("SR-001", "SR-014")]


def test_search_enforces_clearance():
    q = "frequency-hopping spread spectrum in a contested electromagnetic environment"
    open_res = srv.search_requirements(q, "OPEN")
    assert open_res["refused"] is True
    assert "SR-013" not in {c["id"] for c in open_res["contexts"]}

    secret_res = srv.search_requirements(q, "SECRET")
    assert "SR-013" in secret_res["citations"]
