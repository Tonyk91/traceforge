# TraceForge MCP Server

TraceForge speaks the **Model Context Protocol** so any MCP-capable client — Claude Desktop, an
IDE copilot, or an agent orchestrator — can call the traceability and compliance engine as tools.
Access control travels with the protocol: every retrieval-backed tool takes the caller's
`clearance` and enforces need-to-know *inside the retriever*, so an agent wired to this server can
never surface a requirement the caller is not cleared to see.

## Tools

| Tool | Arguments | Returns |
|------|-----------|---------|
| `search_requirements` | `query`, `clearance` (OPEN\|RESTRICTED\|SECRET) | Grounded answer + cited requirement IDs + retrieved contexts. Refuses when no accessible requirement grounds the question. |
| `get_traceability` | `requirement_id` | Bidirectional trace: verifying tests + satisfying design elements. |
| `find_orphans` | — | Requirements with no verifying test; tests referencing no requirement. |
| `check_quality` | — | EARS/INCOSE quality flags per requirement + overall score. |
| `compliance_report` | — | Coverage, orphans, conflicts, duplicates, quality score. |

## Run

```bash
pip install -e ".[mcp]"
python -m traceforge.mcp_server        # stdio server
python -m traceforge.mcp_client_demo   # smoke test: lists tools, proves clearance enforcement
```

## Register in Claude Desktop

Add to `claude_desktop_config.json` (`mcpServers`), using an absolute path and the repo as the
working directory so the dataset resolves:

```json
{
  "mcpServers": {
    "traceforge": {
      "command": "/absolute/path/to/traceforge/.venv/bin/python",
      "args": ["-m", "traceforge.mcp_server"],
      "cwd": "/absolute/path/to/traceforge",
      "env": { "TRACEFORGE_BRONZE": "data/bronze/trus" }
    }
  }
}
```

Point `TRACEFORGE_BRONZE` at another dataset to serve it instead. Set the Azure OpenAI variables
from `.env.example` to have `search_requirements` synthesize with Azure OpenAI; unset, it falls
back to a deterministic extractive answer so the server runs fully offline.

## Access-control proof

The demo asks the same classified probe at two clearances:

```
[OPEN     ] refused=True  citations=[]
[SECRET   ] refused=False citations=['SR-011', 'SR-018', 'SR-012']
```

Same question, same index — the OPEN caller is refused because no requirement *at its clearance*
grounds the answer, while SECRET sees the classified datalink/EW requirements. This is asserted in
`tests/test_mcp.py::test_search_enforces_clearance`.
