"""Bronze ingestion: read raw source docs into typed objects.

This is the deterministic parser used when no Azure OpenAI key is configured. It reads the
structured-prose SRS and the test/design CSVs. The LLM extractor (llm.py) produces the same
`Requirement` objects from free-form prose; both feed the identical silver schema.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .models import Classification, DesignElement, Requirement, TestCase

# **SR-001** (OPEN) — Verification: Test      (verification part optional)
_REQ_HEADER = re.compile(
    r"^\*\*(?P<id>[A-Z]+-\d+)\*\*\s*"
    r"\((?P<cls>OPEN|RESTRICTED|SECRET)\)"
    r"(?:\s*[—\-]\s*Verification:\s*(?P<method>\w+))?\s*$"
)
_SECTION = re.compile(r"^##\s+(?P<sec>.+?)\s*$")


def parse_srs(path: str | Path) -> list[Requirement]:
    """Parse the structured-prose SRS into atomic requirements."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    doc_id = Path(path).stem
    section = ""
    reqs: list[Requirement] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        sec_m = _SECTION.match(line)
        if sec_m:
            section = sec_m.group("sec")
            i += 1
            continue
        m = _REQ_HEADER.match(line)
        if m:
            # requirement text = following non-empty lines until a blank line
            body: list[str] = []
            j = i + 1
            while j < len(lines) and lines[j].strip():
                body.append(lines[j].strip())
                j += 1
            reqs.append(
                Requirement(
                    requirement_id=m.group("id"),
                    section=section,
                    text=" ".join(body),
                    verification_method=m.group("method"),
                    classification=Classification.parse(m.group("cls")),
                    source_ref=f"{doc_id}#{m.group('id')}",
                )
            )
            i = j
            continue
        i += 1
    return reqs


def _split_ids(value: str) -> list[str]:
    return [x.strip() for x in re.split(r"[;,]", value) if x.strip()]


def load_tests(path: str | Path) -> list[TestCase]:
    out: list[TestCase] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append(
                TestCase(
                    test_id=row["test_id"],
                    title=row["title"],
                    covers=_split_ids(row.get("covers", "")),
                    method=row.get("method") or None,
                    status=row.get("status", "unknown"),
                    classification=Classification.parse(row.get("classification", "OPEN")),
                )
            )
    return out


def load_design(path: str | Path) -> list[DesignElement]:
    out: list[DesignElement] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append(
                DesignElement(
                    design_id=row["design_id"],
                    title=row["title"],
                    satisfies=_split_ids(row.get("satisfies", "")),
                    type=row.get("type", ""),
                    classification=Classification.parse(row.get("classification", "OPEN")),
                )
            )
    return out


def load_bronze(root: str | Path = "data/bronze/trus") -> tuple[
    list[Requirement], list[TestCase], list[DesignElement]
]:
    root = Path(root)
    reqs = parse_srs(root / "SRS-TRUS-001.md")
    tests = load_tests(root / "test-cases.csv")
    design = load_design(root / "design-elements.csv")
    return reqs, tests, design
