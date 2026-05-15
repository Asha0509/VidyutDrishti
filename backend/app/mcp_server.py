"""MCP server exposing the copilot's read-only data tools.

The same eight tools the in-app copilot calls (`app.ai.tools`) are served over the
Model Context Protocol, so any MCP client (an IDE, a desktop assistant, another
agent) can ask about the network: queue, meters, transformer balance, alerts,
measured detection quality. Every number still comes from the store; nothing here
writes data or changes a decision.

    pip install -e "backend[mcp]"
    python -m app.mcp_server            # stdio transport, seeds the demo network first
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.ai import tools


def build_server() -> FastMCP:
    """Register every tool in `tools.TOOLS` with the description the copilot uses."""
    server = FastMCP("vidyutdrishti")
    for name, fn in tools.TOOLS.items():
        server.add_tool(fn, name=name, description=tools.SPECS[name]["function"]["description"])
    return server


def main() -> None:
    from app.demo_seed import _seed

    _seed()  # synchronous: clients should not see an empty network
    build_server().run()


if __name__ == "__main__":
    main()
