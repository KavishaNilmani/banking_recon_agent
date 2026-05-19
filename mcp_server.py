"""
MCP Server — Generic Billing Reconciliation Agent
Exposes all 14 generic billing reconciliation tools via the Model Context Protocol (stdio transport).

Configure in Claude Code CLI:  .claude/settings.json  (project-level)
Configure in Claude Desktop:   see claude_desktop_config.json at project root

Run directly for testing:
    python mcp_server.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from src.utils.tool_registry import TOOL_DEFINITIONS, execute_tool


server = Server("generic-billing-recon")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """Expose all 14 generic billing reconciliation MCP tools."""
    return [
        types.Tool(
            name=td["name"],
            description=td["description"],
            inputSchema=td["input_schema"],
        )
        for td in TOOL_DEFINITIONS
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Dispatch a tool call to the generic billing reconciliation engine."""
    result_json = execute_tool(name, arguments or {})
    return [types.TextContent(type="text", text=result_json)]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
