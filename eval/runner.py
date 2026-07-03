"""Golden-set evaluation harness — the numbers that make the compliance claim auditable.

Runs the whole system against ``eval/gold.yaml`` (the seeded defects in the synthetic TRUS
dataset) and scores five capabilities that matter for certification tooling:

    extraction        — did the parser recover every requirement?             (P/R/F1)
    quality           — do the EARS/INCOSE flags match ground truth?          (micro F1)
    traceability      — orphans / conflicts / duplicates found exactly?       (exact match)
    grounding         — answerable Qs answered w/ citations, unanswerable refused
    access_control    — zero requirements surfaced above the caller's clearance   (leaks)

Every metric is checked against a gate; any miss exits non-zero so CI fails the build. The whole
run is deterministic and offline (no Azure needed), so the gate is reproducible.

    python -m eval.runner            # scorecard + gate
    python -m eval.runner --json     # machine-readable, still gated
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from traceforge import ingest, quality, trace
from traceforge.models import Classification
from traceforge.rag import Rag

ROOT = Path(__file__).resolve().parents[1]
BRONZE = ROOT / "data" / "bronze" / "trus"
GOLD = yaml.safe_load((ROOT / "eval" / "gold.yaml").read_text())

# Answerable / unanswerable probes for grounding + faithfulness (OPEN-visible content only).
ANSWERABLE = [
    "What is the required flight endurance of the air vehicle?",
    "What imaging resolution must the electro-optical payload achieve?",
]
UNANSWERABLE = [  # off-domain: no accessible requirement grounds these → must refuse
    "What is the required insulin dosage for diabetic patients using the infusion pump?",
    "What underwater sonar bathymetry mapping accuracy is needed for submarine surveys?",
]


@dataclass
class Metric:
    name: str
    value: float
    gate: float
    unit: str = "F1"
    detail: str = ""
    # A metric passes when value >= gate, except leak counts where value must be <= gate.
    lower_is_better: bool = False

    @property
    def passed(self) -> bool:
        return self.value <= self.gate if self.lower_is_better else self.value >= self.gate


@dataclass
class Scorecard:
    metrics: list[Metric] = field(default_factory=list)

    def add(self, m: Metric) -> None:
        self.metrics.append(m)

    @property
    def passed(self) -> bool:
        return all(m.passed for m in self.metrics)


def _prf(predicted: set[str], gold: set[str]) -> tuple[float, float, float]:
    tp = len(predicted & gold)
    precision = tp / len(predicted) if predicted else (1.0 if not gold else 0.0)
    recall = tp / len(gold) if gold else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def _pairs(items: list) -> set[frozenset]:  # noqa: ANN001
    """Normalize [[a,b], ...] gold/predicted pairs to an order-independent set."""
    return {frozenset(p) for p in items}


def evaluate() -> Scorecard:
    reqs, tests, design = ingest.load_bronze(BRONZE)
    quality.annotate(reqs)
    card = Scorecard()

    # 1. Extraction ------------------------------------------------------------
    parsed_ids = {r.requirement_id for r in reqs}
    gold_ids = set(GOLD["requirement_ids"])
    _, _, f1 = _prf(parsed_ids, gold_ids)
    missing, extra = gold_ids - parsed_ids, parsed_ids - gold_ids
    card.add(Metric("extraction", f1, gate=1.0,
                    detail=f"{len(parsed_ids)}/{len(gold_ids)} ids"
                           + (f" missing={sorted(missing)}" if missing else "")
                           + (f" extra={sorted(extra)}" if extra else "")))

    # 2. Classification accuracy ----------------------------------------------
    gold_cls = {rid: "RESTRICTED" for rid in GOLD["classification"].get("RESTRICTED", [])}
    gold_cls.update({rid: "SECRET" for rid in GOLD["classification"].get("SECRET", [])})
    correct = sum(
        1 for r in reqs
        if r.classification.name == gold_cls.get(r.requirement_id, "OPEN")
    )
    card.add(Metric("classification", correct / len(reqs), gate=1.0, unit="acc",
                    detail=f"{correct}/{len(reqs)} correct"))

    # 3. Quality flags (micro F1 over (req, flag) pairs) -----------------------
    pred_flags = {f"{r.requirement_id}:{f}" for r in reqs for f in r.quality_flags}
    gold_flags = {f"{rid}:{f}" for rid, fs in GOLD["quality_flags"].items() for f in fs}
    _, _, qf1 = _prf(pred_flags, gold_flags)
    card.add(Metric("quality_flags", qf1, gate=0.9,
                    detail=f"pred={len(pred_flags)} gold={len(gold_flags)}"))

    # 4. Traceability ----------------------------------------------------------
    _, _, orphan_r_f1 = _prf(set(trace.orphan_requirements(reqs, tests)),
                             set(GOLD["orphan_requirements"]))
    card.add(Metric("orphan_reqs", orphan_r_f1, gate=1.0))
    _, _, orphan_t_f1 = _prf(set(trace.orphan_tests(reqs, tests)),
                             set(GOLD["orphan_tests"]))
    card.add(Metric("orphan_tests", orphan_t_f1, gate=1.0))

    conflicts = _pairs([list(p) for p in trace.find_conflicts(reqs)])
    gold_conflicts = _pairs([c["pair"] for c in GOLD["conflicts"]])
    card.add(Metric("conflicts", float(conflicts == gold_conflicts), gate=1.0, unit="exact"))

    dupes = _pairs([list(p) for p in trace.find_duplicates(reqs)])
    gold_dupes = _pairs([d["pair"] for d in GOLD["duplicates"]])
    card.add(Metric("duplicates", float(dupes == gold_dupes), gate=1.0, unit="exact"))

    # 5. Grounding / faithfulness ---------------------------------------------
    rag = Rag(str(BRONZE))
    grounded = sum(
        1 for q in ANSWERABLE
        if not (res := rag.answer(q, Classification.OPEN)).refused and res.citations
    )
    refused = sum(1 for q in UNANSWERABLE if rag.answer(q, Classification.OPEN).refused)
    total_q = len(ANSWERABLE) + len(UNANSWERABLE)
    card.add(Metric("grounding", (grounded + refused) / total_q, gate=1.0, unit="acc",
                    detail=f"{grounded}/{len(ANSWERABLE)} answered, "
                           f"{refused}/{len(UNANSWERABLE)} correctly refused"))

    # 6. Access control — leaks must be zero -----------------------------------
    id_to_text = {r.requirement_id: r.text for r in reqs}
    leaks: list[str] = []
    for clr, forbidden in (("OPEN", GOLD["access_control"]["OPEN_must_not_see"]),
                           ("RESTRICTED", GOLD["access_control"]["RESTRICTED_must_not_see"])):
        forbidden_set = set(forbidden)
        for rid in forbidden:  # probe with the classified requirement's own text
            res = rag.answer(id_to_text[rid], Classification.parse(clr))
            seen = ({c["id"] for c in res.contexts} | set(res.citations)) & forbidden_set
            leaks += [f"{clr}<-{s}" for s in seen]
    card.add(Metric("access_control_leaks", float(len(leaks)), gate=0.0, unit="leaks",
                    lower_is_better=True, detail=", ".join(leaks) or "none"))

    return card


def _render(card: Scorecard) -> str:
    rows = []
    width = max(len(m.name) for m in card.metrics)
    for m in card.metrics:
        mark = "PASS" if m.passed else "FAIL"
        val = f"{m.value:.0f}" if m.unit in ("leaks",) else f"{m.value:.3f}"
        gate = f"{m.gate:.0f}" if m.unit in ("leaks",) else f"{m.gate:.2f}"
        cmp = "<=" if m.lower_is_better else ">="
        line = f"  [{mark}] {m.name:<{width}}  {m.unit:<6} {val:>6} (gate {cmp} {gate})"
        if m.detail:
            line += f"  · {m.detail}"
        rows.append(line)
    header = "TraceForge evaluation — golden set (TRUS)"
    footer = "GATE PASSED ✓" if card.passed else "GATE FAILED ✗"
    return "\n".join([header, "-" * len(header), *rows, "", footer])


def main() -> int:
    ap = argparse.ArgumentParser(description="TraceForge golden-set eval harness")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    card = evaluate()
    if args.json:
        print(json.dumps({
            "passed": card.passed,
            "metrics": [
                {"name": m.name, "value": m.value, "gate": m.gate,
                 "unit": m.unit, "passed": m.passed, "detail": m.detail}
                for m in card.metrics
            ],
        }, indent=2))
    else:
        print(_render(card))
    return 0 if card.passed else 1


if __name__ == "__main__":
    sys.exit(main())
