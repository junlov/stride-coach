import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError
from typer.testing import CliRunner

from stride_coach.api import ServerConfig, create_app
from stride_coach.cli import app as cli
from stride_coach.db_models import PairingCodeRow, PairingLimitRow
from stride_coach.pairing import ATTEMPTS_PER_MINUTE, PairingStore, digest, server_url

TOKEN = "synthetic-pairing-token-with-at-least-32-characters"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def api(tmp_path, database):
    def forbidden(*args, **kwargs):
        raise AssertionError("Pairing must not call Garmin")

    config = ServerConfig(
        token=TOKEN, database_url=database, tokens=tmp_path / "tokens", sync_enabled=False
    )
    with TestClient(create_app(config, forbidden)) as client:
        yield client


def issue(api):
    result = api.post("/pairing/codes", headers=HEADERS)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["expires_in"] == 600
    return result.json()["code"]


def exchange(api, code):
    return api.post("/pairing/exchange", json={"code": code})


def test_pairing_once_hash_only_and_no_secrets_in_logs(api, caplog):
    caplog.set_level(logging.DEBUG)
    assert api.post("/pairing/codes").status_code == 401
    assert api.post("/pairing/codes", headers={"Authorization": "Bearer wrong"}).status_code == 401
    code = issue(api)
    pairing = api.app.state.pairing
    with pairing.engine.connect() as db:
        row = db.execute(select(PairingCodeRow.__table__)).one()
        assert row.code_hash == digest(code)
        assert row.token_hash == digest(TOKEN)
        seconds = (row.expires_at - db.scalar(select(func.now()))).total_seconds()
        assert 590 < seconds <= 600
        assert code not in str(row) and TOKEN not in str(row)
    result = exchange(api, code)
    assert result.status_code == 200
    assert result.json() == {"token": TOKEN}
    assert result.headers["cache-control"] == "no-store"
    assert exchange(api, code).status_code == 400
    assert exchange(api, "unknown").status_code == 400
    invalid = api.post("/pairing/exchange", content='{"code":"' + code)
    assert invalid.status_code == 422
    assert code not in invalid.text
    assert code not in caplog.text
    assert TOKEN not in caplog.text


def test_expired_code_and_rotated_token_are_rejected(api, database):
    code = issue(api)
    other = PairingStore(database, TOKEN + "-rotated")
    try:
        assert not other.consume(code)
    finally:
        other.close()
    with api.app.state.pairing.engine.begin() as db:
        db.execute(update(PairingCodeRow).values(expires_at=func.now() - timedelta(seconds=1)))
    assert exchange(api, code).status_code == 400
    issue(api)
    with api.app.state.pairing.engine.connect() as db:
        assert db.scalar(select(func.count()).select_from(PairingCodeRow)) == 1


def test_concurrent_exchange_across_store_instances_has_one_winner(api, database):
    code = issue(api)

    def consume(_):
        store = PairingStore(database, TOKEN)
        try:
            return store.consume(code)
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(consume, range(4))) == 1


def test_rate_limit_includes_malformed_bodies_survives_new_instances_and_resets(api, database):
    code = issue(api)
    for _ in range(ATTEMPTS_PER_MINUTE):
        assert api.post("/pairing/exchange", content="{").status_code == 422
    denied = exchange(api, code)
    assert denied.status_code == 429
    assert denied.headers["retry-after"] == "60"
    assert denied.headers["cache-control"] == "no-store"
    other = PairingStore(database, TOKEN)
    try:
        assert not other.allow_attempt()
    finally:
        other.close()
    with api.app.state.pairing.engine.begin() as db:
        db.execute(update(PairingLimitRow).values(window_start=func.now() - timedelta(minutes=2)))
    assert exchange(api, code).status_code == 200


def test_rate_limit_database_error_is_sanitized(api, monkeypatch):
    def failed():
        raise OperationalError("secret query", None, Exception("secret error"))

    monkeypatch.setattr(api.app.state.pairing, "allow_attempt", failed)
    result = exchange(api, "unknown")
    assert result.status_code == 503
    assert result.json() == {"detail": "Database unavailable"}


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:pass@host",
        "https://x/?q=1",
        "https://x/#x",
        "file:///tmp",
        "https://x:bad",
        "https://has space",
    ],
)
def test_cli_rejects_unsafe_server_urls(url):
    with pytest.raises(ValueError):
        server_url(url)


def test_cli_contacts_server_and_encodes_only_one_time_code(api, monkeypatch):
    import qrcode

    monkeypatch.setenv("STRIDE_COACH_API_TOKEN", TOKEN)
    requests = []
    links = []
    original_add = qrcode.QRCode.add_data

    def add(self, data, *args, **kwargs):
        links.append(data)
        return original_add(self, data, *args, **kwargs)

    def post(url, **kwargs):
        requests.append((url, kwargs))
        result = api.post("/pairing/codes", headers=kwargs["headers"])
        return httpx.Response(
            result.status_code, json=result.json(), request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(qrcode.QRCode, "add_data", add)
    monkeypatch.setattr(httpx, "post", post)
    result = CliRunner().invoke(cli, ["pair", "--server", "https://coach.example.test"])
    assert result.exit_code == 0, result.output
    assert requests[0][0] == "http://127.0.0.1:8000/pairing/codes"
    assert requests[0][1]["follow_redirects"] is False
    assert requests[0][1]["headers"] == HEADERS
    parsed = urlsplit(links[0])
    assert parsed.scheme == "stridecoach" and parsed.netloc == "pair"
    query = parse_qs(parsed.query)
    assert query["server"] == ["https://coach.example.test"]
    assert query["code"][0] in result.output
    assert "10 minutes" in result.output
    assert TOKEN not in result.output and TOKEN not in links[0]
    assert exchange(api, query["code"][0]).status_code == 200


def test_cli_failure_does_not_echo_secrets(monkeypatch):
    monkeypatch.setenv("STRIDE_COACH_API_TOKEN", TOKEN)

    def failed(*args, **kwargs):
        raise httpx.ConnectError(TOKEN)

    monkeypatch.setattr(httpx, "post", failed)
    result = CliRunner().invoke(cli, ["pair", "--server", "https://coach.example.test"])
    assert result.exit_code == 1 and "Pairing failed" in result.output
    assert TOKEN not in result.output
    monkeypatch.delenv("STRIDE_COACH_API_TOKEN")
    assert (
        CliRunner().invoke(cli, ["pair", "--server", "https://coach.example.test"]).exit_code == 1
    )
