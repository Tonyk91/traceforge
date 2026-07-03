"""Typed domain model shared across every layer of the medallion pipeline.

These schemas are the contract between stages: the parser emits `Requirement`s, the
quality engine annotates them, the traceability engine consumes them together with
`TestCase`s and `DesignElement`s. Keeping one schema means a local run and an Azure run
are byte-for-byte comparable.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Optional

from pydantic import BaseModel, Field


class Classification(IntEnum):
    """Ordered clearance levels — order *is* the access-control policy.

    Enforced at retrieval time as ``level(doc) <= level(clearance)``.
    """

    OPEN = 0
    RESTRICTED = 1
    SECRET = 2

    @classmethod
    def parse(cls, value: str | int | "Classification") -> "Classification":
        if isinstance(value, Classification):
            return value
        if isinstance(value, int):
            return cls(value)
        return cls[str(value).strip().upper()]


# Recognised verification methods (DO-178C / MIL-STD verification categories).
VERIFICATION_METHODS = ("Test", "Analysis", "Inspection", "Demonstration")


# Quality flags — deterministic EARS/INCOSE rules (see quality.py).
QUALITY_FLAGS = (
    "AMBIGUOUS",
    "NOT_TESTABLE",
    "NOT_ATOMIC",
    "MISSING_VERIFICATION",
    "WEAK_IMPERATIVE",
    "MISSING_ID",
)


class Requirement(BaseModel):
    requirement_id: str
    section: str = ""
    text: str
    req_type: str = "functional"
    verification_method: Optional[str] = None
    classification: Classification = Classification.OPEN
    quality_flags: list[str] = Field(default_factory=list)
    source_ref: str = ""  # e.g. "SRS-TRUS-001#SR-004"


class TestCase(BaseModel):
    test_id: str
    title: str
    covers: list[str] = Field(default_factory=list)  # requirement IDs claimed
    method: Optional[str] = None
    status: str = "unknown"  # pass | fail | blocked | unknown
    classification: Classification = Classification.OPEN


class DesignElement(BaseModel):
    design_id: str
    title: str
    satisfies: list[str] = Field(default_factory=list)  # requirement IDs
    type: str = ""
    classification: Classification = Classification.OPEN


class TraceLink(BaseModel):
    source: str      # requirement / test / design id
    target: str
    kind: str        # verifies | satisfied_by | conflict | duplicate


class ComplianceReport(BaseModel):
    total_requirements: int
    verified: int
    coverage: float
    orphan_requirements: list[str]
    orphan_tests: list[str]
    conflicts: list[tuple[str, str]]
    duplicates: list[tuple[str, str]]
    quality_score: float
    flags_by_requirement: dict[str, list[str]]
