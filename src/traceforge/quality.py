"""Deterministic requirement-quality analysis (EARS / INCOSE rules).

The quality verdict must be reproducible and auditable, so it is pure Python — no LLM.
Each rule returns a flag from ``models.QUALITY_FLAGS`` and is unit-tested against the
seeded defects in ``eval/gold.yaml``.
"""

from __future__ import annotations

import re

from .models import VERIFICATION_METHODS, Requirement

# Vague, unverifiable terms (INCOSE "Guide to Writing Requirements", ambiguity list).
WEAK_WORDS = {
    "user-friendly", "adequate", "appropriate", "as appropriate", "sufficient",
    "robust", "flexible", "fast", "quick", "minimal", "maximal", "efficient",
    "easy", "reasonable", "state-of-the-art", "adverse", "normal", "etc",
    "and/or", "as required", "if possible", "where practical", "acceptable",
    "good", "better", "seamless", "intuitive",
}

# Non-binding modal verbs used where "shall" is required for a mandatory requirement.
WEAK_IMPERATIVES = {"should", "may", "will", "could", "might"}

# A measurable criterion: a number, tolerance, or comparison. Used for testability.
_MEASURABLE = re.compile(
    r"\b\d+(\.\d+)?\s*(%|percent|s|sec|second|seconds|min|minute|minutes|h|hour|hours|"
    r"m|metre|metres|meter|meters|km|kilometre|kilometres|kg|gb|gigabyte|gigabytes|"
    r"°|deg|degree|degrees|km/h|kts|cep|hz|khz|mhz)\b|×?10[⁻\-]\d|1e[\-−]?\d",
    re.IGNORECASE,
)
_SHALL = re.compile(r"\bshall\b", re.IGNORECASE)
_CONJUNCTION = re.compile(r",\s+and\b|\band\b.*\band\b", re.IGNORECASE)


def _has_measurable(text: str) -> bool:
    return bool(_MEASURABLE.search(text))


def find_weak_words(text: str) -> list[str]:
    low = text.lower()
    hits = []
    for w in WEAK_WORDS:
        # word-boundary match, allowing hyphenated terms
        if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", low):
            hits.append(w)
    return sorted(hits)


def analyze(req: Requirement) -> list[str]:
    """Return the sorted list of quality flags for a requirement."""
    flags: set[str] = set()
    text = req.text.strip()

    if not req.requirement_id:
        flags.add("MISSING_ID")

    weak = find_weak_words(text)
    if weak:
        flags.add("AMBIGUOUS")

    # Weak imperative: a binding requirement that doesn't use "shall".
    lowered = text.lower()
    if not _SHALL.search(text) and any(
        re.search(rf"\b{w}\b", lowered) for w in WEAK_IMPERATIVES
    ):
        flags.add("WEAK_IMPERATIVE")

    method = (req.verification_method or "").strip()
    if method not in VERIFICATION_METHODS:
        flags.add("MISSING_VERIFICATION")

    # Not testable: a vague term with no measurable acceptance criterion. A declared
    # verification method does NOT rescue this — you still can't write a pass/fail test
    # for "user-friendly" or "adverse weather".
    if weak and not _has_measurable(text):
        flags.add("NOT_TESTABLE")

    # Not atomic: more than one "shall" clause, or a conjunction of distinct actions.
    shall_count = len(_SHALL.findall(text))
    if shall_count > 1 or (shall_count == 1 and _looks_compound(text)):
        flags.add("NOT_ATOMIC")

    return sorted(flags)


def _looks_compound(text: str) -> bool:
    """Heuristic for a single-'shall' requirement bundling multiple actions.

    e.g. "shall capture imagery, transmit it ... and store it" — three verbs joined by
    commas + a trailing 'and'. We require an Oxford-style ", and" plus >=2 commas so we
    don't flag ordinary compound noun phrases.
    """
    after_shall = re.split(r"\bshall\b", text, flags=re.IGNORECASE, maxsplit=1)[-1]
    comma_and = ", and " in after_shall.lower() or ", and\n" in after_shall.lower()
    return comma_and and after_shall.count(",") >= 2


def annotate(requirements: list[Requirement]) -> list[Requirement]:
    """Attach quality flags to each requirement in place and return the list."""
    for req in requirements:
        req.quality_flags = analyze(req)
    return requirements


def quality_score(requirements: list[Requirement]) -> float:
    """Fraction of requirements with no quality flags (0..1)."""
    if not requirements:
        return 1.0
    clean = sum(1 for r in requirements if not r.quality_flags)
    return round(clean / len(requirements), 4)
