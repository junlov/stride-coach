"""Stdio MCP transport over the same service as CLI and HTTP."""

import argparse
import os
from contextlib import contextmanager

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .service import Coach
from .storage import Store


def create_server(database_url: str | None = None) -> FastMCP:
    server = FastMCP("stride-coach")
    annotations = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )

    @contextmanager
    def read():
        store = Store(database_url, read_only=True)
        try:
            yield Coach(store)
        finally:
            store.close()

    @server.tool(annotations=annotations)
    def plan() -> dict:
        """Read the local training plan, targets, and baseline warnings."""
        with read() as coach:
            return coach.plan().model_dump(mode="json")

    @server.tool(annotations=annotations)
    def week(number: int) -> dict:
        """Read one week's workouts and measured completion."""
        with read() as coach:
            return coach.week(number).model_dump(mode="json")

    @server.tool(annotations=annotations)
    def compliance() -> list[dict]:
        """Read weekly session matching; inferred matches are labeled."""
        with read() as coach:
            return [m.model_dump(mode="json") for m in coach.compliance()]

    @server.tool(annotations=annotations)
    def load() -> list[dict]:
        """Read running Banister TRIMP and missing-HR counts by week."""
        with read() as coach:
            return [m.model_dump(mode="json") for m in coach.load()]

    @server.tool(annotations=annotations)
    def propose_adjustment(number: int) -> dict:
        """Preview deterministic rules from local data; never apply or push changes.

        A preview can include an incomplete week. The adapt operation enforces date and sync
        coverage before saving. No coaching text or arbitrary commands become executable input.
        """
        with read() as coach:
            return coach.propose_adjustment(number).model_dump(mode="json")

    return server


def main():
    parser = argparse.ArgumentParser(description="stride-coach local MCP server")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    args = parser.parse_args()
    create_server(args.database_url).run(transport="stdio")


if __name__ == "__main__":
    main()
