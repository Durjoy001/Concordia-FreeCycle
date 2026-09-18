"""FreeCycle MCP server - registers the five agent tools.

Transports:
  stdio  the orchestrator spawns this file as a subprocess (bare-metal dev, tests)
  http   streamable HTTP on /mcp, which is how the docker-compose `mcp-server`
         service is reached, since stdio cannot cross a container boundary.

Run:  python server.py --transport http --host 0.0.0.0 --port 8765
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from claude import ToolError
from tools import TOOL_MODULES

SERVER_NAME = "freecycle-agent-tools"
SERVER_VERSION = "0.1.0"

logger = logging.getLogger("freecycle.mcp")

INSTRUCTIONS = """Tools for Concordia FreeCycle, a student free-item giveaway board.

Typical order of use:
  * a new listing with a photo -> create_listing_from_photo to draft its fields
  * any new listing -> flag_prohibited first; if it is clean, match_wishlist
  * a hand-written listing whose category looks wrong -> classify_item
  * a claim the owner just accepted -> draft_coordination

match_wishlist and draft_coordination read the database themselves, so they need
only ids. Never notify a student about a listing that flag_prohibited flagged."""

TOOLS_BY_NAME = {module.NAME: module for module in TOOL_MODULES}


def build_tools() -> list[types.Tool]:
    """The tool list advertised to clients, with strict input and output schemas."""
    return [
        types.Tool(
            name=module.NAME,
            title=module.NAME.replace("_", " ").title(),
            description=module.DESCRIPTION,
            inputSchema=module.INPUT_SCHEMA,
            outputSchema=module.OUTPUT_SCHEMA,
        )
        for module in TOOL_MODULES
    ]


async def on_list_tools(
    _context: Any, _params: types.PaginatedRequestParams | None
) -> types.ListToolsResult:
    return types.ListToolsResult(tools=build_tools())


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)], isError=True
    )


async def on_call_tool(
    _context: Any, params: types.CallToolRequestParams
) -> types.CallToolResult:
    """Dispatch to a tool module, returning both structured and text content.

    Structured content is what the orchestrator consumes; the JSON text block is
    there so any MCP client that ignores structuredContent still sees the result.
    """
    module = TOOLS_BY_NAME.get(params.name)
    if module is None:
        return _error(f"Unknown tool {params.name!r}.")

    arguments = dict(params.arguments or {})
    started = time.perf_counter()
    try:
        result = await module.run(arguments)
    except ToolError as exc:
        _log_call(params.name, started, ok=False, error=str(exc))
        return _error(str(exc))
    except KeyError as exc:
        _log_call(params.name, started, ok=False, error=f"missing argument {exc}")
        return _error(f"Missing required argument: {exc}.")
    except Exception as exc:  # noqa: BLE001 - never kill the server on one bad call
        logger.exception("tool %s raised", params.name)
        _log_call(params.name, started, ok=False, error=repr(exc))
        return _error(f"{params.name} failed: {exc}")

    usage = result.pop("_usage", {})
    _log_call(params.name, started, ok=True, usage=usage)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(result))],
        structuredContent=result,
    )


def _log_call(
    tool: str,
    started: float,
    *,
    ok: bool,
    usage: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """One JSON line per tool call - the server half of the observability story."""
    record: dict[str, Any] = {
        "event": "mcp_tool_call",
        "tool": tool,
        "ok": ok,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    if usage:
        record["input_tokens"] = usage.get("input_tokens", 0)
        record["output_tokens"] = usage.get("output_tokens", 0)
    if error:
        record["error"] = error
    logger.info(json.dumps(record))


def build_server() -> Server[Any]:
    return Server(
        SERVER_NAME,
        version=SERVER_VERSION,
        instructions=INSTRUCTIONS,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


async def run_stdio(server: Server[Any]) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run_http(server: Server[Any], host: str, port: int) -> None:
    import uvicorn

    uvicorn.run(
        server.streamable_http_app(streamable_http_path="/mcp", host=host),
        host=host,
        port=port,
        log_level=os.environ.get("MCP_LOG_LEVEL", "info"),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="FreeCycle MCP tool server")
    parser.add_argument("--transport", choices=("stdio", "http"), default="http")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    # On stdio the protocol owns stdout, so logs must go to stderr.
    logging.basicConfig(
        level=os.environ.get("MCP_LOG_LEVEL", "INFO").upper(),
        format="%(message)s",
        stream=sys.stderr,
    )

    server = build_server()
    if args.transport == "stdio":
        asyncio.run(run_stdio(server))
    else:
        run_http(server, args.host, args.port)


if __name__ == "__main__":
    main()
