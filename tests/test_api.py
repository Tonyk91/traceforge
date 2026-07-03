"""Smoke tests for the FastAPI serving layer."""

from fastapi.testclient import TestClient

from traceforge.api import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_report():
    r = client.get("/report").json()
    assert r["total_requirements"] == 24
    assert r["orphan_requirements"] == ["SR-007", "SR-021", "SR-023"]


def test_ask_enforces_clearance():
    q = "frequency-hopping spread spectrum in a contested electromagnetic environment"
    open_res = client.post("/ask", json={"question": q, "clearance": "OPEN"}).json()
    assert open_res["refused"] is True
    assert "SR-013" not in {c["id"] for c in open_res["contexts"]}

    secret_res = client.post("/ask", json={"question": q, "clearance": "SECRET"}).json()
    assert "SR-013" in secret_res["citations"]


def test_trace_endpoint():
    r = client.get("/requirements/SR-011/trace").json()
    assert "TC-010" in r["verified_by"]
    assert "DE-04" in r["satisfied_by"]


def test_matrix_withholds_above_clearance():
    open_m = client.get("/matrix?clearance=OPEN").json()
    open_ids = {row["requirement_id"] for row in open_m["rows"]}
    assert open_m["visible_requirements"] < open_m["total_requirements"]
    assert open_m["withheld"] > 0
    # SR-013 is SECRET — an OPEN caller must not see it anywhere in the matrix.
    assert "SR-013" not in open_ids
    assert all(row["classification"] == "OPEN" for row in open_m["rows"])

    secret_m = client.get("/matrix?clearance=SECRET").json()
    assert secret_m["withheld"] == 0
    assert "SR-013" in {row["requirement_id"] for row in secret_m["rows"]}


def test_dashboard_served():
    r = client.get("/ui/")
    assert r.status_code == 200 and "TraceForge" in r.text
