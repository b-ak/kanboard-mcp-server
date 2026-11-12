"""Server construction and CLI entry point."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from fastmcp import FastMCP

from . import __version__
from .auth import build_auth
from .client import KanboardClient
from .config import ConfigError, KanboardConfig, ServerConfig
from .tools import register_tools

INSTRUCTIONS = """\
Tools for a self-hosted Kanboard instance.
- Call list_projects first to find project IDs; get_board shows columns and open tasks.
- Priority: higher number = more important (Kanboard default range 0-3).
- Use search_tasks with Kanboard filter syntax (e.g. 'status:open assignee:me due:<=today').
- Use get_task to read the full context (comments, subtasks, attachments) before summarising.
- Log progress with add_comment; move work across the board with move_task.
"""


def create_server(
    kanboard: KanboardConfig | None = None,
    server: ServerConfig | None = None,
) -> FastMCP:
    kanboard = kanboard or KanboardConfig.from_env()
    server = server or ServerConfig()
    mcp = FastMCP(
        name="kanboard",
        instructions=INSTRUCTIONS,
        version=__version__,
        auth=build_auth(server),
    )
    register_tools(mcp, KanboardClient(kanboard))
    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="kanboard-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "http"], help="Overrides MCP_TRANSPORT")
    parser.add_argument("--host", help="Overrides MCP_HOST")
    parser.add_argument("--port", type=int, help="Overrides MCP_PORT")
    parser.add_argument("--env-file", help="Load variables from this .env file first")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    if args.env_file:
        from dotenv import load_dotenv

        load_dotenv(args.env_file, override=False)
    for flag, var in (("transport", "MCP_TRANSPORT"), ("host", "MCP_HOST"), ("port", "MCP_PORT")):
        if getattr(args, flag) is not None:
            os.environ[var] = str(getattr(args, flag))

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,  # stdout is reserved for the stdio MCP protocol
    )

    try:
        server_cfg = ServerConfig.from_env()
        mcp = create_server(KanboardConfig.from_env(), server_cfg)
    except ConfigError as exc:
        sys.exit(f"Configuration error: {exc}")

    if server_cfg.transport == "http":
        mcp.run(transport="http", host=server_cfg.host, port=server_cfg.port, show_banner=False)
    else:
        mcp.run(show_banner=False)
