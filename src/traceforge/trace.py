"""Traceability engine: links, orphans, conflicts, duplicates, coverage.

Design intent (see docs/architecture.md): the LLM *proposes* conflict/duplicate candidates
by understanding which requirements address the same measurable attribute; a deterministic
check then *confirms* the contradiction so the compliance verdict is reproducible. The
functions here are that deterministic core, plus an offline candidate heuristic so the whole
thing runs without an LLM (and in CI).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from itertools import combinations

from .models import DesignElement, Requirement, TestCase, TraceLink

# ── bound extraction ─────────────────────────────────────────────────────────

_LOWER = r"(?:at least|not less than|no less than|not fewer than|minimum of|>=|≥|greater than)"
_UPPER = r"(?:not exceed|not to exceed|no more than|at most|maximum of|<=|≤|less than|shall not exceed|within)"
_UNIT = (
    r"(hours?|minutes?|seconds?|kilometres?|kilometers?|km|metres?|meters?|m|kilograms?|kg|"
    r"gigabytes?|gb|percent|%)"
)
_NUM = r"(\d+(?:\.\d+)?)"

_LOWER_RE = re.compile(rf"{_LOWER}\s+{_NUM}\s*{_UNIT}", re.IGNORECASE)
_UPPER_RE = re.compile(rf"{_UPPER}\s+{_NUM}\s*{_UNIT}", re.IGNORECASE)
_RATE_RE = re.compile(rf"per\s+\w*\s*{_UNIT}", re.IGNORECASE)

_UNIT_CANON = {
    "hours": "hour", "hour": "hour",
    "minutes": "minute", "minute": "minute",
    "seconds": "second", "second": "second",
    "kilometres": "km", "kilometers": "km", "km": "km",
    "metres": "m", "meters": "m", "meter": "m", "metre": "m", "m": "m",
    "kilograms": "kg", "kilogram": "kg", "kg": "kg",
    "gigabytes": "gb", "gigabyte": "gb", "gb": "gb",
    "percent": "pct", "%": "pct",
}

# Words that are not distinctive enough to establish two requirements share an attribute.
_STOP = {
    "the", "a", "an", "of", "for", "to", "and", "or", "with", "in", "on", "at", "by",
    "shall", "system", "air", "vehicle", "not", "less", "than", "least", "no", "more",
    "exceed", "within", "above", "below", "level", "mean", "sea", "range", "single",
    "nominal", "using", "during", "per", "provide", "maintain", "achieve", "reach",
    "continuous",  # generic; kept out so it doesn't inflate matches on its own
}


def _bounds(text: str) -> list[tuple[str, float, str]]:
    """Return [(direction, value, canonical_unit)]; skips rate expressions like 'per hour'."""
    rate_units = {_UNIT_CANON.get(u.lower(), u.lower()) for u in _RATE_RE.findall(text)}
    out: list[tuple[str, float, str]] = []
    for direction, rx in (("lower", _LOWER_RE), ("upper", _UPPER_RE)):
        for value, unit in rx.findall(text):
            cu = _UNIT_CANON.get(unit.lower(), unit.lower())
            if cu in rate_units:
                continue
            out.append((direction, float(value), cu))
    return out


def _salient(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {w for w in words if w not in _STOP and len(w) > 2 and not w.isdigit()}


# ── links ────────────────────────────────────────────────────────────────────

def build_links(
    reqs: list[Requirement], tests: list[TestCase], design: list[DesignElement]
) -> list[TraceLink]:
    valid = {r.requirement_id for r in reqs}
    links: list[TraceLink] = []
    for t in tests:
        for rid in t.covers:
            if rid in valid:
                links.append(TraceLink(source=t.test_id, target=rid, kind="verifies"))
    for d in design:
        for rid in d.satisfies:
            if rid in valid:
                links.append(TraceLink(source=d.design_id, target=rid, kind="satisfied_by"))
    return links


def orphan_requirements(reqs: list[Requirement], tests: list[TestCase]) -> list[str]:
    """Requirements with no verifying test (passing or otherwise)."""
    valid = {r.requirement_id for r in reqs}
    covered = {rid for t in tests for rid in t.covers if rid in valid}
    return sorted(r.requirement_id for r in reqs if r.requirement_id not in covered)


def orphan_tests(reqs: list[Requirement], tests: list[TestCase]) -> list[str]:
    """Tests that reference no existing requirement."""
    valid = {r.requirement_id for r in reqs}
    return sorted(t.test_id for t in tests if not (set(t.covers) & valid))


def verified_requirements(reqs: list[Requirement], tests: list[TestCase]) -> set[str]:
    """Requirements with at least one passing verification."""
    valid = {r.requirement_id for r in reqs}
    return {
        rid
        for t in tests
        if t.status == "pass"
        for rid in t.covers
        if rid in valid
    }


# ── conflicts & duplicates ─────────────────────────────────────────────────────

def find_conflicts(reqs: list[Requirement], min_shared: int = 2) -> list[tuple[str, str]]:
    """Pairs with contradictory numeric bounds on a shared measurable attribute.

    A pair conflicts when: same canonical unit, a lower bound on one and an upper bound on
    the other with lower_value > upper_value, and >= ``min_shared`` distinctive words in
    common (so 'ceiling in metres' and 'resolution in metres' aren't mistaken for the same
    attribute).
    """
    out: list[tuple[str, str]] = []
    for a, b in combinations(reqs, 2):
        ba, bb = _bounds(a.text), _bounds(b.text)
        if not ba or not bb:
            continue
        shared = _salient(a.text) & _salient(b.text)
        if len(shared) < min_shared:
            continue
        if _contradicts(ba, bb) or _contradicts(bb, ba):
            out.append((a.requirement_id, b.requirement_id))
    return sorted(out)


def _contradicts(
    x: list[tuple[str, float, str]], y: list[tuple[str, float, str]]
) -> bool:
    """True if x has a lower bound and y an upper bound on the same unit with lower > upper."""
    for dx, vx, ux in x:
        if dx != "lower":
            continue
        for dy, vy, uy in y:
            if dy == "upper" and ux == uy and vx > vy:
                return True
    return False


def find_duplicates(reqs: list[Requirement], threshold: float = 0.85) -> list[tuple[str, str]]:
    """Near-identical requirements (normalized text similarity)."""
    out: list[tuple[str, str]] = []
    for a, b in combinations(reqs, 2):
        ratio = SequenceMatcher(None, _norm(a.text), _norm(b.text)).ratio()
        if ratio >= threshold:
            out.append((a.requirement_id, b.requirement_id))
    return sorted(out)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", text.lower())).strip()
