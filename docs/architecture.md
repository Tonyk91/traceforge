# Architecture

TraceForge is a medallion lakehouse with a serving layer on top. Each stage is a pure
transform with a typed contract, so it can be tested in isolation and swapped between a local
and an Azure implementation without touching callers.

## Data flow

### Bronze — raw, immutable
Source documents exactly as received:
- `SRS-TRUS-001.md` — System Requirements Specification (natural-language "shall" statements,
  grouped by section, each carrying an ID and a classification marking).
- `test-cases.csv` — verification test cases with the requirement IDs each claims to cover.
- `design-elements.csv` — design/architecture elements with the requirements they satisfy.

Stored in Azure Blob (`BRONZE_CONTAINER`) in production, or `./data/bronze` locally. Bronze is
append-only and is the single source of truth for re-processing.

### Silver — structured, cleansed, classified
The parse stage turns prose into one atomic row per requirement:

```
requirement_id, section, text, req_type, verification_method,
classification, quality_flags[], source_ref
```

- **Extraction**: `AZURE_OPENAI_CHAT_DEPLOYMENT` extracts atomic requirements from prose; when no
  Azure key is present, a deterministic parser splits on requirement IDs / "shall" boundaries.
  Both emit the identical schema, so downstream code is agnostic.
- **Quality**: deterministic EARS/INCOSE rules attach `quality_flags` (see below).
- **Classification**: the marking on each requirement (`OPEN | RESTRICTED | SECRET`) is carried
  forward verbatim — it is never inferred or dropped.

Materialized as Parquet + a DuckDB view (`silver.requirements`). DuckDB is a portable stand-in
for Delta/Databricks: the same SQL runs against a Databricks SQL warehouse in production.

### Gold — serving
Two derived assets:
1. **Retrieval index** — each requirement/test embedded and indexed for hybrid search
   (vector + BM25, fused with Reciprocal Rank Fusion, then reranked). Azure AI Search in
   production; an in-process numpy + `rank-bm25` index locally.
2. **Traceability graph** — edges `requirement → test` (verifies) and `requirement → design`
   (satisfied_by), plus derived `conflict` and `duplicate` edges. Feeds coverage rollups and
   orphan detection.

## Quality rules (silver)

Deterministic, unit-tested, standard-derived:

| Flag                     | Rule                                                              |
|--------------------------|------------------------------------------------------------------|
| `AMBIGUOUS`              | weak/unverifiable words (e.g. *user-friendly, fast, appropriate, minimal, robust, etc.*) |
| `NOT_TESTABLE`           | no measurable criterion and no verification method               |
| `NOT_ATOMIC`             | multiple "shall" clauses / conjunction of independent conditions |
| `MISSING_VERIFICATION`   | no verification method (Test/Analysis/Inspection/Demonstration)  |
| `WEAK_IMPERATIVE`        | uses *should/may/will* instead of *shall* for a binding requirement |
| `MISSING_ID`             | requirement text with no traceable identifier                    |

## Traceability & compliance (gold)

- **Coverage** = requirements with ≥1 passing verification / total requirements.
- **Orphan requirement** = requirement with no linked test.
- **Orphan test** = test whose claimed requirement IDs don't exist (or are unlinked).
- **Conflict** = two requirements with contradictory measurable bounds on the same attribute
  (semantic candidate generation + a deterministic numeric/negation check to confirm).
- **Duplicate** = near-identical requirements (high semantic similarity, same attribute).

The LLM proposes *candidates* for conflicts/duplicates; a deterministic check confirms them, so
the final compliance verdict is reproducible and auditable.

## Access control

`classification` is enforced at retrieval time. A request carries a `clearance`; the retriever
filters the candidate set to `level(doc) <= level(clearance)` **before** ranking, so higher-marked
content can never leak into a lower-clearance answer, its citations, or the ranking signal. The
gold index stores classification as a filterable field (Azure AI Search `$filter`; a pre-filter
predicate locally). Leakage is tested explicitly in the eval suite.

## Serving

- **FastAPI** — `/ask`, `/report`, `/requirements/{id}/trace`, `/orphans`, `/quality`.
- **MCP server** — the same operations as MCP tools (`search_requirements`, `get_traceability`,
  `find_orphans`, `check_quality`, `compliance_report`) for agent integration.
- **UI** — compliance dashboard (coverage, orphans, quality, traceability matrix) + grounded chat.

## Orchestration

The pipeline is expressed as an Airflow-style DAG:

```
ingest_bronze → parse_silver → analyze_quality → classify → build_gold_index → link_traceability → rollup_compliance
```

Locally it runs in-process (`traceforge pipeline run`); the same task functions are importable as
Airflow tasks for a scheduled production run.
