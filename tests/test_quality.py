"""Quality engine must reproduce the seeded defects in eval/gold.yaml exactly."""

from pathlib import Path

import yaml

from traceforge import ingest, quality

ROOT = Path(__file__).resolve().parents[1]
GOLD = yaml.safe_load((ROOT / "eval" / "gold.yaml").read_text())


def _reqs():
    return quality.annotate(ingest.parse_srs(ROOT / "data/bronze/trus/SRS-TRUS-001.md"))


def test_all_requirements_extracted():
    ids = {r.requirement_id for r in _reqs()}
    assert ids == set(GOLD["requirement_ids"])


def test_quality_flags_match_gold():
    got = {r.requirement_id: sorted(r.quality_flags) for r in _reqs() if r.quality_flags}
    want = {k: sorted(v) for k, v in GOLD["quality_flags"].items()}
    assert got == want


def test_classification_carried_from_source():
    by_id = {r.requirement_id: r for r in _reqs()}
    for level, ids in GOLD["classification"].items():
        for rid in ids:
            assert by_id[rid].classification.name == level
