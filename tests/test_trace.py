"""Traceability engine must reproduce the seeded traceability defects in gold.yaml."""

from pathlib import Path

import yaml

from traceforge import ingest, trace

ROOT = Path(__file__).resolve().parents[1]
GOLD = yaml.safe_load((ROOT / "eval" / "gold.yaml").read_text())


def _data():
    return ingest.load_bronze(ROOT / "data/bronze/trus")


def test_orphan_requirements():
    reqs, tests, _ = _data()
    assert trace.orphan_requirements(reqs, tests) == sorted(GOLD["orphan_requirements"])


def test_orphan_tests():
    reqs, tests, _ = _data()
    assert trace.orphan_tests(reqs, tests) == sorted(GOLD["orphan_tests"])


def test_conflicts():
    reqs, _, _ = _data()
    want = {tuple(sorted(c["pair"])) for c in GOLD["conflicts"]}
    got = {tuple(sorted(p)) for p in trace.find_conflicts(reqs)}
    assert got == want


def test_duplicates():
    reqs, _, _ = _data()
    want = {tuple(sorted(d["pair"])) for d in GOLD["duplicates"]}
    got = {tuple(sorted(p)) for p in trace.find_duplicates(reqs)}
    assert got == want


def test_no_false_conflicts_across_shared_units():
    # metres appear in ceiling, resolution and accuracy requirements; none should conflict.
    reqs, _, _ = _data()
    pairs = {frozenset(p) for p in trace.find_conflicts(reqs)}
    assert frozenset({"SR-006", "SR-008"}) not in pairs
    assert frozenset({"SR-006", "SR-015"}) not in pairs
