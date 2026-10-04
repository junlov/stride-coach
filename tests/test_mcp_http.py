import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from stride_coach.api import ServerConfig, create_app
from stride_coach.service import AdaptRequest, Coach, SyncRequest

TOKEN = "synthetic-mcp-token-with-at-least-32-characters"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}
TOOLS = {
    "plan",
    "week",
    "compliance",
    "load",
    "propose_adjustment",
    "today_workout",
    "current_week",
    "status",
}


class TestMCPPreflight:
    @pytest.fixture
    def database(self):
        return "postgresql+psycopg://unused:synthetic-password@localhost/unused"

    @pytest.mark.parametrize("allowed", [True, False])
    def test_protocol_header(self, database, tmp_path, allowed):
        origin = "https://coach.example.test"
        config = ServerConfig(
            token=TOKEN,
            database_url=database,
            tokens=tmp_path / "tokens",
            cors_origins=[origin],
        )
        client = TestClient(create_app(config))
        try:
            response = client.options(
                "/mcp/",
                headers={
                    "Origin": origin if allowed else "https://untrusted.example.test",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": (
                        "authorization,content-type,mcp-protocol-version"
                    ),
                },
            )
            if allowed:
                assert response.status_code == 200
                assert response.headers["access-control-allow-origin"] == origin
                headers = {
                    header.strip().lower()
                    for header in response.headers["access-control-allow-headers"].split(",")
                }
                assert {"authorization", "content-type", "mcp-protocol-version"} <= headers
            else:
                assert response.status_code == 400
                assert "access-control-allow-origin" not in response.headers
        finally:
            client.close()
            client.app.state.garmin_connection.close()


@pytest.fixture
def api(store, tmp_path):
    config = ServerConfig(
        token=TOKEN,
        database_url=store.url,
        tokens=tmp_path / "tokens",
        timezone="America/Sao_Paulo",
        cors_origins=["https://coach.example.test"],
    )
    with TestClient(create_app(config), base_url="https://coach.example.test") as client:
        yield client


def rpc(api, method, params=None):
    response = api.post(
        "/mcp/",
        headers=HEADERS,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


def call(api, name, arguments=None):
    result = rpc(api, "tools/call", {"name": name, "arguments": arguments or {}})
    assert not result.get("isError"), result
    # List outputs use one text block per item; structuredContent has a result wrapper.
    if "structuredContent" in result:
        data = result["structuredContent"]
        return data["result"] if set(data) == {"result"} else data
    return json.loads(result["content"][0]["text"])


def freeze(monkeypatch, instant):
    import stride_coach.mcp as mcp

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)

    monkeypatch.setattr(mcp, "datetime", Clock)


def test_auth_covers_all_mcp_methods_and_redirects(api):
    for path in ("/mcp", "/mcp/", "/mcp/anything"):
        for method in ("GET", "POST", "DELETE", "PUT", "OPTIONS"):
            for authorization in (None, "Bearer invalid", f"Basic {TOKEN}"):
                headers = {"Authorization": authorization} if authorization else {}
                response = api.request(method, path, headers=headers, follow_redirects=False)
                assert response.status_code == 401
                assert response.headers["www-authenticate"] == "Bearer"
    assert api.post(f"/mcp/?token={TOKEN}").status_code == 401
    api.cookies.set("token", TOKEN)
    assert api.post("/mcp/").status_code == 401


def test_remote_origin_and_handshake(api):
    response = api.post(
        "/mcp/",
        headers={**HEADERS, "Origin": "https://untrusted.example.test"},
        json={},
    )
    assert response.status_code == 403
    result = rpc(
        api,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "synthetic-test", "version": "1"},
        },
    )
    assert result["serverInfo"]["name"] == "stride-coach"
    response = api.post(
        "/mcp/",
        headers={**HEADERS, "Origin": "https://coach.example.test"},
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert response.status_code == 202
    assert api.get("/mcp/", headers={**HEADERS, "Accept": "application/json"}).status_code == 406
    assert api.delete("/mcp/", headers=HEADERS).status_code == 405


def test_every_remote_tool_reads_fixtures_without_writes(api, store, monkeypatch):
    service = Coach(store)
    start = store.plan().setup.start
    monday = start + timedelta(weeks=1)
    service.sync(
        SyncRequest(
            since=start - timedelta(days=7), until=monday - timedelta(days=1), activities=[]
        ),
        today=monday,
    )
    applied = service.adapt(AdaptRequest(week=2, apply=True), today=monday)
    freeze(monkeypatch, datetime.combine(monday, datetime.min.time(), UTC) + timedelta(hours=12))
    expected = {
        "plan": service.plan().model_dump(mode="json"),
        "week": service.week(2).model_dump(mode="json"),
        "compliance": [m.model_dump(mode="json") for m in service.compliance()],
        "load": [m.model_dump(mode="json") for m in service.load()],
        "propose_adjustment": service.propose_adjustment(3).model_dump(mode="json"),
        "today_workout": service.today_workout(monday).model_dump(mode="json"),
        "current_week": service.current_week(monday).model_dump(mode="json"),
        "status": service.status().model_dump(mode="json"),
    }

    def forbidden(*args, **kwargs):
        raise AssertionError("MCP must not enter write or Garmin operations")

    for name in ("initialize", "sync", "adapt", "push", "remove"):
        monkeypatch.setattr(Coach, name, forbidden)
    listed = rpc(api, "tools/list")["tools"]
    assert {t["name"] for t in listed} == TOOLS
    assert all(t["annotations"]["readOnlyHint"] for t in listed)
    for name, data in expected.items():
        args = (
            {"number": 2}
            if name == "week"
            else {"number": 3}
            if name == "propose_adjustment"
            else {}
        )
        assert call(api, name, args) == data
    assert expected["status"]["adjustments"] == [applied.model_dump(mode="json")]
    for name in ("initialize", "sync", "adapt", "push", "remove", "apply", "garmin_login"):
        result = rpc(api, "tools/call", {"name": name, "arguments": {"apply": True}})
        assert result["isError"]
        assert "Unknown tool" in result["content"][0]["text"]
    assert service.plan().model_dump(mode="json") == expected["plan"]
    assert service.status().model_dump(mode="json") == expected["status"]


def test_timezone_rest_days_and_outside_plan(api, store, monkeypatch):
    plan = store.plan()
    # Monday UTC is still Sunday in the configured athlete timezone.
    instant = datetime.combine(plan.setup.start, datetime.min.time(), UTC) + timedelta(hours=1)
    freeze(monkeypatch, instant)
    assert call(api, "today_workout")["status"] == "outside_plan"
    assert call(api, "current_week")["week"] is None
    for offset in range(7):
        day = plan.setup.start + timedelta(days=offset)
        freeze(monkeypatch, datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=12))
        today = call(api, "today_workout")
        expected = [w for w in plan.workouts if w.day == day]
        assert today["day"] == str(day)
        assert today["status"] == ("workout" if expected else "rest")
        assert [w["workout"]["id"] for w in today["workouts"]] == [w.id for w in expected]
        assert call(api, "current_week")["week"] == 1
    freeze(
        monkeypatch,
        datetime.combine(plan.setup.race_date, datetime.min.time(), UTC) + timedelta(hours=12),
    )
    assert call(api, "today_workout")["status"] == "outside_plan"
    assert call(api, "current_week")["view"] is None
    status = call(api, "status")
    assert status["sync"] is None and status["adjustments"] == []


def test_tool_database_session_enforces_read_only(api, store, monkeypatch):
    from sqlalchemy import text

    before = store.plan()

    def accidental_write(self):
        self.store.connection.execute(text("DELETE FROM plans"))

    monkeypatch.setattr(Coach, "plan", accidental_write)
    result = rpc(api, "tools/call", {"name": "plan"})
    assert result["isError"]
    assert "read-only transaction" in result["content"][0]["text"]
    assert store.plan() == before
