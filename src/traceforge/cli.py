"""TraceForge command-line interface."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from . import ingest, quality
from .models import Classification

app = typer.Typer(add_completion=False, help="Requirements traceability & compliance copilot.")
console = Console()

BRONZE = "data/bronze/trus"


@app.command("requirements")
def list_requirements(bronze: str = BRONZE) -> None:
    """List parsed requirements."""
    reqs = ingest.parse_srs(f"{bronze}/SRS-TRUS-001.md")
    table = Table(title=f"Requirements ({len(reqs)})")
    table.add_column("ID", style="cyan")
    table.add_column("Cls")
    table.add_column("Verif")
    table.add_column("Text", overflow="fold")
    for r in reqs:
        table.add_row(
            r.requirement_id,
            r.classification.name,
            r.verification_method or "—",
            r.text[:90] + ("…" if len(r.text) > 90 else ""),
        )
    console.print(table)


@app.command("quality")
def quality_report(bronze: str = BRONZE) -> None:
    """Run deterministic EARS/INCOSE quality analysis."""
    reqs = quality.annotate(ingest.parse_srs(f"{bronze}/SRS-TRUS-001.md"))
    flagged = [r for r in reqs if r.quality_flags]
    table = Table(title="Requirement quality — flagged items")
    table.add_column("ID", style="cyan")
    table.add_column("Flags", style="yellow")
    table.add_column("Text", overflow="fold")
    for r in flagged:
        table.add_row(r.requirement_id, ", ".join(r.quality_flags), r.text[:80])
    console.print(table)
    score = quality.quality_score(reqs)
    console.print(
        f"\n[bold]Quality score:[/bold] {score:.0%}  "
        f"({len(reqs) - len(flagged)}/{len(reqs)} clean, {len(flagged)} flagged)"
    )


@app.command("pipeline")
def pipeline(action: str = typer.Argument("run")) -> None:
    """Run the medallion pipeline (bronze → silver → gold)."""
    if action != "run":
        raise typer.BadParameter("only 'run' is supported")
    from .pipeline import run_pipeline

    run_pipeline(BRONZE)


@app.command("report")
def report(bronze: str = BRONZE) -> None:
    """Compliance report: coverage, orphans, conflicts, duplicates, quality."""
    from .pipeline import compliance

    rep = compliance(bronze)
    _print_report(rep)


@app.command("ask")
def ask(
    question: str,
    clearance: str = typer.Option("OPEN", help="Caller clearance: OPEN|RESTRICTED|SECRET"),
    bronze: str = BRONZE,
) -> None:
    """Ask a grounded question, enforcing the caller's clearance."""
    from .rag import answer

    result = answer(question, Classification.parse(clearance), bronze)
    console.print(f"\n[bold]{result.answer}[/bold]\n")
    if result.citations:
        console.print("[dim]Sources:[/dim] " + ", ".join(result.citations))


def _print_report(rep) -> None:  # noqa: ANN001
    console.print("\n[bold]Compliance report[/bold]")
    console.print(f"  Requirements:      {rep.total_requirements}")
    console.print(f"  Verified:          {rep.verified}  ([bold]{rep.coverage:.0%}[/bold] coverage)")
    console.print(f"  Quality score:     {rep.quality_score:.0%}")
    console.print(f"  Orphan reqs:       {', '.join(rep.orphan_requirements) or '—'}")
    console.print(f"  Orphan tests:      {', '.join(rep.orphan_tests) or '—'}")
    console.print(
        "  Conflicts:         "
        + ("; ".join(f"{a}↔{b}" for a, b in rep.conflicts) or "—")
    )
    console.print(
        "  Duplicates:        "
        + ("; ".join(f"{a}≈{b}" for a, b in rep.duplicates) or "—")
    )


if __name__ == "__main__":
    app()
