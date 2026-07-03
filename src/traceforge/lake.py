"""Medallion lake materialization on DuckDB.

DuckDB is a portable, in-process stand-in for a Databricks/Delta lakehouse: the silver
tables and gold rollups here are plain SQL that runs unchanged against a Databricks SQL
warehouse in production. Silver is materialized to Parquet (the medallion silver format)
and registered as DuckDB views.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from .models import DesignElement, Requirement, TestCase, TraceLink


class Lake:
    def __init__(self, root: str | Path = "data") -> None:
        self.root = Path(root)
        self.silver = self.root / "silver"
        self.gold = self.root / "gold"
        self.silver.mkdir(parents=True, exist_ok=True)
        self.gold.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.gold / "traceforge.duckdb"))

    # ── silver ────────────────────────────────────────────────────────────────
    def write_silver(
        self,
        reqs: list[Requirement],
        tests: list[TestCase],
        design: list[DesignElement],
        links: list[TraceLink],
    ) -> None:
        con = self.con
        con.execute("CREATE OR REPLACE TABLE requirements AS SELECT * FROM (VALUES " +
                    self._values([
                        (r.requirement_id, r.section, r.text, r.req_type,
                         r.verification_method, r.classification.name,
                         ",".join(r.quality_flags), r.source_ref)
                        for r in reqs
                    ]) + ") AS t(requirement_id, section, text, req_type, "
                        "verification_method, classification, quality_flags, source_ref)")
        con.execute("CREATE OR REPLACE TABLE tests AS SELECT * FROM (VALUES " +
                    self._values([
                        (t.test_id, t.title, ",".join(t.covers), t.method or "",
                         t.status, t.classification.name)
                        for t in tests
                    ]) + ") AS t(test_id, title, covers, method, status, classification)")
        con.execute("CREATE OR REPLACE TABLE trace_links AS SELECT * FROM (VALUES " +
                    self._values([(lk.source, lk.target, lk.kind) for lk in links]) +
                    ") AS t(source, target, kind)")
        # Persist silver as Parquet (the canonical silver artifact).
        con.execute(f"COPY requirements TO '{self.silver / 'requirements.parquet'}' (FORMAT PARQUET)")
        con.execute(f"COPY tests TO '{self.silver / 'tests.parquet'}' (FORMAT PARQUET)")

    # ── gold rollups (pure SQL) ─────────────────────────────────────────────────
    def coverage(self) -> tuple[int, int, float]:
        """(verified, total, ratio) computed in SQL over the trace graph."""
        total = self.con.execute("SELECT count(*) FROM requirements").fetchone()[0]
        verified = self.con.execute(
            """
            SELECT count(DISTINCT r.requirement_id)
            FROM requirements r
            JOIN trace_links l ON l.target = r.requirement_id AND l.kind = 'verifies'
            JOIN tests t ON t.test_id = l.source AND t.status = 'pass'
            """
        ).fetchone()[0]
        ratio = round(verified / total, 4) if total else 1.0
        return verified, total, ratio

    def coverage_by_classification(self) -> list[tuple[str, int, int]]:
        return self.con.execute(
            """
            SELECT r.classification,
                   count(DISTINCT CASE WHEN t.status = 'pass' THEN r.requirement_id END) AS verified,
                   count(DISTINCT r.requirement_id) AS total
            FROM requirements r
            LEFT JOIN trace_links l ON l.target = r.requirement_id AND l.kind = 'verifies'
            LEFT JOIN tests t ON t.test_id = l.source
            GROUP BY r.classification
            ORDER BY r.classification
            """
        ).fetchall()

    @staticmethod
    def _values(rows: list[tuple]) -> str:
        def lit(v) -> str:  # noqa: ANN001
            return "'" + str(v).replace("'", "''") + "'"
        return ", ".join("(" + ", ".join(lit(c) for c in row) + ")" for row in rows)

    def close(self) -> None:
        self.con.close()
