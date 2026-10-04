import asyncio
import json
from datetime import date, timedelta

from typer.testing import CliRunner

from stride_coach.cli import app
from stride_coach.mcp import create_server
from stride_coach.service import Coach, SyncRequest

runner = CliRunner()


def test_cli_offline_full_workflow(tmp_path, database):
    db = database
    today = date.today()
    start = today + timedelta(days=(-today.weekday()) % 7)
    end = start + timedelta(weeks=12)
    args = ["--database-url", str(db)]
    result = runner.invoke(app, args + ["init", "10k", str(end), "--start", str(start)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["sessions"] == 36
    result = runner.invoke(app, args + ["plan", "--week", "1"])
    assert result.exit_code == 0, result.output
    workout = json.loads(result.stdout)["workouts"][0]["workout"]["id"]
    for command in [
        ["push", "--workout", workout, "--dry-run"],
        ["push", "--week", "1"],
        ["remove", "--dry-run"],
        ["status"],
    ]:
        result = runner.invoke(app, args + command)
        assert result.exit_code == 0, result.output
    activities = tmp_path / "activities.json"
    activities.write_text("[]")
    result = runner.invoke(
        app,
        args
        + ["sync", "--activities", str(activities), "--since", str(today - timedelta(days=28))],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, args + ["push", "--apply", "--dry-run"])
    assert result.exit_code == 1
    result = runner.invoke(app, args + ["init", "5k", str(end)])
    assert result.exit_code == 1 and "already exists" in result.output


def test_mcp_lists_only_safe_tools_and_calls_them(store):
    async def exercise():
        server = create_server(store.url)
        tools = await server.list_tools()
        assert {t.name for t in tools} == {
            "plan",
            "week",
            "compliance",
            "load",
            "propose_adjustment",
        }
        assert all(t.annotations.readOnlyHint for t in tools)
        before = store.plan()
        for name, args in [
            ("plan", {}),
            ("week", {"number": 1}),
            ("compliance", {}),
            ("load", {}),
            ("propose_adjustment", {"number": 2}),
        ]:
            result = await server.call_tool(name, args)
            assert result
        assert store.plan() == before
        assert not store.adjustment(2)

    asyncio.run(exercise())


def test_mcp_missing_plan_does_not_create(database):
    import pytest

    from stride_coach.storage import Store

    async def exercise():
        server = create_server(database)
        with pytest.raises(Exception, match="No plan"):
            await server.call_tool("plan", {})
        store = Store(database, read_only=True)
        try:
            with pytest.raises(ValueError, match="No plan"):
                store.plan()
        finally:
            store.close()

    asyncio.run(exercise())


def test_mcp_stdio_handshake_and_proposal(store):
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def exercise():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "stride_coach.mcp", "--database-url", str(store.url)],
        )
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert len(listed.tools) == 5
                result = await session.call_tool("propose_adjustment", {"number": 2})
                assert not result.isError
                data = json.loads(result.content[0].text)
                assert data["preview_only"] is True
                assert data["adjustment"]["factor"] == 0.75

    asyncio.run(exercise())


def test_cli_adapt_positional_week_preview_and_apply(store, monkeypatch):
    import stride_coach.service as service

    monday = store.plan().setup.start + timedelta(weeks=1)

    class Clock(date):
        @classmethod
        def today(cls):
            return monday

    monkeypatch.setattr(service, "date", Clock)
    Coach(store).sync(SyncRequest(since=monday - timedelta(days=14), activities=[]), today=monday)
    args = ["--database-url", str(store.url), "adapt", "2"]
    preview = runner.invoke(app, args)
    assert preview.exit_code == 0, preview.output
    proposal = json.loads(preview.stdout)
    assert not proposal["applied"]
    assert store.adjustment(2) is None
    applied = runner.invoke(
        app,
        args + ["--apply", "--proposal-fingerprint", proposal["inputs"]["proposal_fingerprint"]],
    )
    assert applied.exit_code == 0, applied.output
    assert json.loads(applied.stdout)["applied"]
    assert store.adjustment(2).applied
