"""Medallion pipeline orchestration.

Expressed as an ordered DAG of pure task functions:

    ingest_bronze → parse/quality (silver) → build gold index → link traceability → rollup

Run in-process here; the same task functions import cleanly as Airflow tasks for a scheduled
production run.
"""

from __future__ import annotations

from rich.console import Console

from . import ingest, quality, trace
from .lake import Lake
from .models import ComplianceReport

console = Console()


def _build(bronze: str):
    reqs, tests, design = ingest.load_bronze(bronze)
    quality.annotate(reqs)
    links = trace.build_links(reqs, tests, design)
    return reqs, tests, design, links


def run_pipeline(bronze: str) -> ComplianceReport:
    console.print("[bold]TraceForge pipeline[/bold]  bronze → silver → gold")
    reqs, tests, design, links = _build(bronze)
    console.print(f"  bronze      : {len(reqs)} reqs, {len(tests)} tests, {len(design)} design")

    lake = Lake()
    lake.write_silver(reqs, tests, design, links)
    console.print(f"  silver      : materialized to Parquet + DuckDB ({len(reqs)} rows)")

    verified, total, ratio = lake.coverage()  # gold rollup in SQL
    console.print(f"  gold        : coverage {verified}/{total} = {ratio:.0%} (SQL rollup)")
    for cls, v, t in lake.coverage_by_classification():
        console.print(f"                {cls:<10} {v}/{t} verified")
    lake.close()

    rep = _report(reqs, tests, design)
    console.print(
        f"  compliance  : {len(rep.orphan_requirements)} orphan reqs, "
        f"{len(rep.conflicts)} conflicts, {len(rep.duplicates)} duplicates, "
        f"quality {rep.quality_score:.0%}"
    )
    return rep


def _report(reqs, tests, design) -> ComplianceReport:  # noqa: ANN001
    verified = trace.verified_requirements(reqs, tests)
    total = len(reqs)
    return ComplianceReport(
        total_requirements=total,
        verified=len(verified),
        coverage=round(len(verified) / total, 4) if total else 1.0,
        orphan_requirements=trace.orphan_requirements(reqs, tests),
        orphan_tests=trace.orphan_tests(reqs, tests),
        conflicts=trace.find_conflicts(reqs),
        duplicates=trace.find_duplicates(reqs),
        quality_score=quality.quality_score(reqs),
        flags_by_requirement={r.requirement_id: r.quality_flags for r in reqs if r.quality_flags},
    )


def compliance(bronze: str) -> ComplianceReport:
    reqs, tests, design, _ = _build(bronze)
    return _report(reqs, tests, design)
