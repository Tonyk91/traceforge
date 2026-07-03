"""Smoke-test client for the TraceForge MCP server.

Spawns the server over stdio, lists its tools, and calls each one — including the access-control
proof: the same probe at OPEN vs SECRET clearance returns different (allowed) evidence. Run:

    python -m traceforge.mcp_client_demo
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _text(result) -> str:  # noqa: ANN001
    """Flatten an MCP tool result's content blocks to text."""
    return "".join(getattr(c, "text", "") for c in result.content)


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "traceforge.mcp_server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("Tools:", ", ".join(t.name for t in tools.tools))

            print("\n— compliance_report —")
            print(_text(await session.call_tool("compliance_report", {}))[:400])

            print("\n— find_orphans —")
            print(_text(await session.call_tool("find_orphans", {})))

            print("\n— get_traceability SR-004 —")
            print(_text(await session.call_tool("get_traceability", {"requirement_id": "SR-004"})))

            print("\n— access control: same probe, two clearances —")
            probe = "What are the classified electronic warfare and datalink range requirements?"
            for clr in ("OPEN", "SECRET"):
                res = await session.call_tool(
                    "search_requirements", {"query": probe, "clearance": clr}
                )
                data = json.loads(_text(res))
                print(f"  [{clr:9}] refused={data['refused']} citations={data['citations']}")


if __name__ == "__main__":
    asyncio.run(main())
