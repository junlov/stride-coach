import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from stride_coach.api import ServerConfig, create_app
from stride_coach.garmin import GarminError
from stride_coach.models import Activity
from stride_coach.service import Coach
from stride_coach.storage import Store

TOKEN = "offline-test-token-with-at-least-32-characters"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def api(tmp_path):
    config = ServerConfig(
        token=TOKEN, db=tmp_path / "api.db", cors_origins=["https://coach.example.test"]
    )

    def forbidden_client(path):
        raise AssertionError("An offline preview must not initialize Garmin")

    return TestClient(create_app(config, client_factory=forbidden_client))


def create_goal(api, setup):
    result = api.post("/goal", json={"setup": setup.model_dump(mode="json")}, headers=HEADERS)
    assert result.status_code == 200, result.text
    return result.json()


def test_auth_required_before_database_access(api):
    for method, path in [
        ("get", "/plan"),
        ("get", "/weeks/1"),
        ("get", "/status"),
        ("get", "/compliance"),
        ("get", "/load"),
        ("get", "/openapi.json"),
        ("post", "/goal"),
        ("post", "/push"),
        ("post", "/sync"),
        ("post", "/adapt"),
        ("post", "/remove"),
        ("post", "/adjustments/propose/2"),
    ]:
        response = getattr(api, method)(path)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        response = getattr(api, method)(path, headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401
    assert api.get("/plan?token=" + TOKEN).status_code == 401


def test_api_shared_service_views_and_safe_default_push(api, setup, monkeypatch):
    import stride_coach.service as service

    class Clock(date):
        @classmethod
        def today(cls):
            return setup.start

    monkeypatch.setattr(service, "date", Clock)
    result = create_goal(api, setup)
    assert result["sessions"] > 0
    for endpoint in ["/plan", "/weeks/1", "/status", "/compliance", "/load"]:
        response = api.get(endpoint, headers=HEADERS)
        assert response.status_code == 200, response.text
    response = api.post("/push", json={"week": 1}, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert all(r["action"] == "preview" for r in response.json())
    assert api.post("/remove", json={}, headers=HEADERS).status_code == 200
    assert (
        api.post("/push", json={"apply": True, "dry_run": True}, headers=HEADERS).status_code == 400
    )
    assert (
        api.post("/remove", json={"apply": True, "dry_run": True}, headers=HEADERS).status_code
        == 400
    )
    assert api.get("/weeks/99", headers=HEADERS).status_code == 400
    assert (
        api.post(
            "/goal", json={"setup": setup.model_dump(mode="json")}, headers=HEADERS
        ).status_code
        == 400
    )


def test_api_sync_propose_apply_and_repeat(api, setup, monkeypatch):
    import stride_coach.service as service

    class Clock(date):
        @classmethod
        def today(cls):
            return setup.start + timedelta(weeks=1)

    monkeypatch.setattr(service, "date", Clock)
    create_goal(api, setup)
    response = api.post("/adapt", json={"week": 2}, headers=HEADERS)
    assert response.status_code == 400 and "Sync" in response.json()["detail"]
    body = {
        "since": str(setup.start - timedelta(weeks=1)),
        "until": str(Clock.today() - timedelta(days=1)),
        "activities": [],
    }
    response = api.post("/sync", json=body, headers=HEADERS)
    assert response.status_code == 200, response.text
    proposal = api.post("/adjustments/propose/2", headers=HEADERS).json()
    assert proposal["preview_only"]
    assert proposal["adjustment"]["factor"] == 0.75
    proposal = api.post("/adapt", json={"week": 2}, headers=HEADERS).json()
    assert not proposal["applied"]
    body = {"week": 2, "apply": True}
    applied = api.post("/adapt", json=body, headers=HEADERS)
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"]
    assert api.post("/adapt", json=body, headers=HEADERS).json() == applied.json()
    assert len(api.get("/status", headers=HEADERS).json()["adjustments"]) == 1
    invalid = api.post("/sync", json={"since": "2099-01-01"}, headers=HEADERS)
    assert invalid.status_code == 400


def test_api_garmin_write_requires_explicit_apply(tmp_path, setup, monkeypatch):
    import stride_coach.service as service

    class Clock(date):
        @classmethod
        def today(cls):
            return setup.start

    monkeypatch.setattr(service, "date", Clock)
    attempts = []

    def client(path):
        attempts.append(path)
        raise GarminError("Saved tokens unavailable")

    api = TestClient(create_app(ServerConfig(token=TOKEN, db=tmp_path / "api.db"), client))
    create_goal(api, setup)
    assert api.post("/push", json={"week": 1}, headers=HEADERS).status_code == 200
    assert not attempts
    result = api.post("/push", json={"week": 1, "apply": True}, headers=HEADERS)
    assert result.status_code == 502 and len(attempts) == 1


def test_api_input_validation_and_cors(api, setup):
    invalid = {"setup": {**setup.model_dump(mode="json"), "days_per_week": 9}}
    assert api.post("/goal", json=invalid, headers=HEADERS).status_code == 422
    assert api.post("/adapt", json={"week": 0}, headers=HEADERS).status_code == 422
    allowed = api.options(
        "/push",
        headers={
            "Origin": "https://coach.example.test",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert allowed.headers["access-control-allow-origin"] == "https://coach.example.test"
    denied = api.options(
        "/push",
        headers={
            "Origin": "https://untrusted.example.test",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_server_configuration_requires_token_and_exact_origins(monkeypatch):
    monkeypatch.delenv("STRIDE_COACH_API_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        ServerConfig.from_env()
    with pytest.raises(ValidationError):
        ServerConfig(token=TOKEN, cors_origins=["*"])
    monkeypatch.setenv("STRIDE_COACH_API_TOKEN", TOKEN)
    monkeypatch.setenv("STRIDE_COACH_CORS_ORIGINS", "https://one.test,https://two.test")
    config = ServerConfig.from_env()
    assert TOKEN not in repr(config)
    assert config.cors_origins == ["https://one.test", "https://two.test"]


def test_committed_openapi_matches_application(api):
    result = api.get("/openapi.json", headers=HEADERS)
    assert result.status_code == 200
    schema = result.json()
    assert schema == json.loads(Path("docs/openapi.json").read_text())
    assert "CoachBearer" in schema["components"]["securitySchemes"]
    for path in schema["paths"].values():
        for operation in path.values():
            assert operation["security"] == [{"CoachBearer": []}]


def test_http_and_direct_service_agree(api, setup, tmp_path):
    create_goal(api, setup)
    store = Store(tmp_path / "api.db", read_only=True)
    try:
        service = Coach(store)
        expected = {
            "/plan": service.plan(),
            "/weeks/1": service.week(1),
            "/status": service.status(),
        }
        for path, value in expected.items():
            assert api.get(path, headers=HEADERS).json() == value.model_dump(mode="json")
        assert api.get("/compliance", headers=HEADERS).json() == [
            m.model_dump(mode="json") for m in service.compliance()
        ]
    finally:
        store.close()


def test_store_read_only_rejects_writes(store):
    import sqlite3

    read = Store(store.path, read_only=True)
    try:
        assert Coach(read).plan() == store.plan()
        with pytest.raises(sqlite3.OperationalError):
            read.save_sync(
                [Activity(id="1", day="2026-10-03", distance_km=5, duration_min=30)],
                "2026-10-01",
                "2026-10-03",
            )
    finally:
        read.close()
