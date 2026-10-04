import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient

import stride_coach.api as api_module
import stride_coach.mcp as mcp_module
from stride_coach.api import ServerConfig, create_app
from stride_coach.garmin_auth import TokenVault
from stride_coach.service import Coach

TOKEN = "synthetic-mcp-token-with-at-least-32-characters"


@pytest.fixture
def database():
    return "postgresql+psycopg://unused:synthetic-password@localhost/unused"


@pytest.mark.parametrize("stall,fail", [("open", False), ("read", False), ("read", True)])
def test_api_responds_during_mcp_read(database, tmp_path, monkeypatch, stall, fail):
    entered = threading.Event()
    release = threading.Event()
    expired = threading.Event()
    calls = []

    def record(stage):
        calls.append((stage, threading.get_ident()))
        if stage == stall:
            entered.set()
            if not release.wait(timeout=5):
                expired.set()

    class BlockingStore:
        def __init__(self, url, *, read_only):
            assert url == database
            assert read_only is True
            record("open")

        def close(self):
            record("close")

    class Result:
        def model_dump(self, *, mode):
            assert mode == "json"
            record("serialize")
            return {"plan_id": "synthetic-plan"}

    def status(coach):
        assert isinstance(coach.store, BlockingStore)
        record("read")
        if fail:
            raise ValueError("synthetic read failure")
        return Result()

    monkeypatch.setattr(mcp_module, "Store", BlockingStore)
    monkeypatch.setattr(Coach, "status", status)
    monkeypatch.setattr(api_module, "upgrade", lambda url: None)
    monkeypatch.setattr(TokenVault, "locked", lambda self: nullcontext())
    config = ServerConfig(token=TOKEN, database_url=database, tokens=tmp_path / "tokens")

    async def loop_thread():
        return threading.get_ident()

    with TestClient(create_app(config)) as client, ThreadPoolExecutor(max_workers=1) as pool:
        event_loop_thread = client.portal.call(loop_thread)
        pending = pool.submit(
            client.post,
            "/mcp/",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "status", "arguments": {}},
            },
        )
        try:
            assert entered.wait(timeout=5)
            response = client.post("/mcp/")
            assert response.status_code == 401
            assert response.headers["www-authenticate"] == "Bearer"
            assert not expired.is_set()
            assert not pending.done()
        finally:
            release.set()
        response = pending.result(timeout=5)

    assert response.status_code == 200
    result = response.json()["result"]
    if fail:
        assert result["isError"]
        assert "synthetic read failure" in result["content"][0]["text"]
    else:
        assert not result.get("isError")
        assert json.loads(result["content"][0]["text"]) == {"plan_id": "synthetic-plan"}
    assert [stage for stage, _ in calls] == (
        ["open", "read", "close"] if fail else ["open", "read", "serialize", "close"]
    )
    worker_threads = {thread for _, thread in calls}
    assert len(worker_threads) == 1
    assert event_loop_thread not in worker_threads
