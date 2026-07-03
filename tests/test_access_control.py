"""Classification-aware access control must never leak content above the caller's clearance.

We probe with the *text of the classified requirements themselves* — the strongest possible
retrieval pull — and assert the protected IDs appear in neither the contexts nor the citations.
"""

from pathlib import Path

import yaml

from traceforge import ingest
from traceforge.models import Classification
from traceforge.rag import Rag

ROOT = Path(__file__).resolve().parents[1]
BRONZE = ROOT / "data/bronze/trus"
GOLD = yaml.safe_load((ROOT / "eval" / "gold.yaml").read_text())


def _rag():
    return Rag(str(BRONZE))


def _probe_text(rid: str) -> str:
    reqs, _, _ = ingest.load_bronze(BRONZE)
    return next(r.text for r in reqs if r.requirement_id == rid)


def test_open_never_sees_above_open():
    rag = _rag()
    forbidden = set(GOLD["access_control"]["OPEN_must_not_see"])
    for rid in forbidden:
        res = rag.answer(_probe_text(rid), Classification.OPEN)
        seen = {c["id"] for c in res.contexts} | set(res.citations)
        assert not (seen & forbidden), f"OPEN query leaked {seen & forbidden} for probe {rid}"


def test_restricted_never_sees_secret():
    rag = _rag()
    forbidden = set(GOLD["access_control"]["RESTRICTED_must_not_see"])
    for rid in forbidden:
        res = rag.answer(_probe_text(rid), Classification.RESTRICTED)
        seen = {c["id"] for c in res.contexts} | set(res.citations)
        assert not (seen & forbidden), f"RESTRICTED query leaked {seen & forbidden} for probe {rid}"


def test_secret_can_see_secret():
    # The same probe at SECRET clearance must surface the SECRET requirement.
    rag = _rag()
    res = rag.answer(_probe_text("SR-013"), Classification.SECRET)
    assert "SR-013" in ({c["id"] for c in res.contexts} | set(res.citations))
    assert not res.refused
