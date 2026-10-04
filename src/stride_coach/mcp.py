"""Read-only stdio and Streamable HTTP MCP over the shared coaching service."""

import argparse
import os
from collections.abc import Callable
from datetime import datetime
from typing import TypeVar
from zoneinfo import ZoneInfo

from anyio import to_thread
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .service import Coach
from .storage import Store

T = TypeVar("T")


def create_server(
    database_url: str | None = None, *, timezone: str | None = None, remote_http: bool = False
) -> FastMCP:
    zone = ZoneInfo(timezone or os.getenv("TZ", "UTC"))
    server = FastMCP(
        "stride-coach",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        # The mounted API enforces bearer auth and exact Origins before MCP runs.
        # Its HTTPS proxy owns host routing, so localhost-only SDK defaults do not apply.
        transport_security=(
            TransportSecuritySettings(enable_dns_rebinding_protection=False)
            if remote_http
            else None
        ),
    )
    annotations = ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
    )

    async def read(operation: Callable[[Coach], T]) -> T:
        def execute():
            store = Store(database_url, read_only=True)
            try:
                return operation(Coach(store))
            finally:
                store.close()

        return await to_thread.run_sync(execute)

    @server.tool(annotations=annotations)
    async def plan() -> dict:
        """Read the local training plan, targets, and baseline warnings."""
        return await read(lambda coach: coach.plan().model_dump(mode="json"))

    @server.tool(annotations=annotations)
    async def week(number: int) -> dict:
        """Read one week's workouts and measured completion."""
        return await read(lambda coach: coach.week(number).model_dump(mode="json"))

    @server.tool(annotations=annotations)
    async def today_workout() -> dict:
        """Read today's workouts in the server timezone, or an explicit rest/outside-plan status."""
        return await read(
            lambda coach: coach.today_workout(datetime.now(zone).date()).model_dump(mode="json")
        )

    @server.tool(annotations=annotations)
    async def current_week() -> dict:
        """Read this week's workouts and measured completion; null week/view outside the plan."""
        return await read(
            lambda coach: coach.current_week(datetime.now(zone).date()).model_dump(mode="json")
        )

    @server.tool(annotations=annotations)
    async def status() -> dict:
        """Read stored sync coverage and applied plan changes with their saved reasons.

        Sync is a covered date range, not the time of the last sync attempt. Null means
        no stored coverage. Adjustments are saved changes, not new proposals. Never syncs.
        """
        return await read(lambda coach: coach.status().model_dump(mode="json"))

    @server.tool(annotations=annotations)
    async def compliance() -> list[dict]:
        """Read weekly session matching; inferred matches are labeled."""
        return await read(lambda coach: [m.model_dump(mode="json") for m in coach.compliance()])

    @server.tool(annotations=annotations)
    async def load() -> list[dict]:
        """Read running Banister TRIMP and missing-HR counts by week."""
        return await read(lambda coach: [m.model_dump(mode="json") for m in coach.load()])

    @server.tool(annotations=annotations)
    async def propose_adjustment(number: int) -> dict:
        """Preview deterministic rules from local data; never apply or push changes.

        A preview can include an incomplete week. The adapt operation enforces date and sync
        coverage before saving. No coaching text or arbitrary commands become executable input.
        """
        return await read(lambda coach: coach.propose_adjustment(number).model_dump(mode="json"))

    return server


def main():
    parser = argparse.ArgumentParser(description="stride-coach local MCP server")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    args = parser.parse_args()
    create_server(args.database_url).run(transport="stdio")


if __name__ == "__main__":
    main()
