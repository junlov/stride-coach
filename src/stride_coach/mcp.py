"""Read-only stdio and Streamable HTTP MCP over the shared coaching service."""

import argparse
import os
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .service import Coach
from .storage import Store


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
    def today_workout() -> dict:
        """Read today's workouts in the server timezone, or an explicit rest/outside-plan status."""
        with read() as coach:
            return coach.today_workout(datetime.now(zone).date()).model_dump(mode="json")

    @server.tool(annotations=annotations)
    def current_week() -> dict:
        """Read this week's workouts and measured completion; null week/view outside the plan."""
        with read() as coach:
            return coach.current_week(datetime.now(zone).date()).model_dump(mode="json")

    @server.tool(annotations=annotations)
    def status() -> dict:
        """Read stored sync coverage and applied plan changes with their saved reasons.

        Sync is a covered date range, not the time of the last sync attempt. Null means
        no stored coverage. Adjustments are saved changes, not new proposals. Never syncs.
        """
        with read() as coach:
            return coach.status().model_dump(mode="json")

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
