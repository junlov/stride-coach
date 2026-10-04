"""Exercise real serialization and HTTP boundaries with fake Garmin responses only."""

import json
import logging
import time

import pytest
import requests
from fastapi.testclient import TestClient
from garth import sso
from garth.auth_tokens import OAuth1Token, OAuth2Token
from garth.http import Client
from typer.testing import CliRunner

from stride_coach.api import ServerConfig, create_app
from stride_coach.cli import app
from stride_coach.garmin import GarminClient
from stride_coach.garmin_auth import GarminConnection, GarminError, StoredSession

PASSWORD = "synthetic-password-not-for-storage"
HEADERS = {"Authorization": "Bearer " + "synthetic-bearer-" * 3}


def tokens(expiry=None):
    return (
        OAuth1Token(oauth_token="synthetic-oauth1", oauth_token_secret="synthetic-secret"),
        OAuth2Token(
            scope="test",
            jti="test",
            token_type="Bearer",
            access_token="synthetic-access",
            refresh_token="synthetic-refresh",
            expires_in=3600,
            expires_at=expiry if expiry is not None else int(time.time()) + 3600,
            refresh_token_expires_in=86400,
            refresh_token_expires_at=int(time.time()) + 86400,
        ),
    )


@pytest.fixture
def fake_garmin(monkeypatch):
    calls = {"login": 0, "mfa": 0, "refresh": 0}

    def login(email, password, *, client, return_on_mfa):
        calls["login"] += 1
        assert return_on_mfa and client.retries == 0
        response = requests.Response()
        response.request = requests.Request(
            "POST", "https://synthetic.test", data={"password": password}
        ).prepare()
        response._content = b"synthetic MFA page"
        response.status_code = 200
        client.last_resp = response
        calls["client"] = client
        if email == "wrong@example.test":
            raise RuntimeError(password)
        if email == "mfa@example.test":
            return "needs_mfa", {"client": client, "signin_params": {}}
        return tokens()

    def resume(state, code):
        calls["mfa"] += 1
        assert state["client"].last_resp.request.body is None
        if code != "123456":
            raise RuntimeError(PASSWORD)
        return tokens()

    def exchange(oauth1, client):
        calls["refresh"] += 1
        assert client.retries == 0
        return tokens()[1]

    monkeypatch.setattr(sso, "login", login)
    monkeypatch.setattr(sso, "resume_login", resume)
    monkeypatch.setattr(sso, "exchange", exchange)
    monkeypatch.setattr(
        Client, "user_profile", property(lambda self: {"fullName": "Synthetic Runner"})
    )
    return calls


@pytest.fixture
def api(tmp_path, fake_garmin):
    config = ServerConfig(
        token="synthetic-bearer-" * 3, db=tmp_path / "coach.db", tokens=tmp_path / "tokens"
    )
    with TestClient(create_app(config)) as client:
        yield client
    client.app.state.garmin_connection.close()


def login(api, email="runner@example.test"):
    return api.post("/garmin/login", json={"email": email, "password": PASSWORD}, headers=HEADERS)


def test_login_status_disconnect_and_secret_boundaries(api, tmp_path, fake_garmin, caplog):
    caplog.set_level(logging.DEBUG)
    assert api.get("/garmin/status", headers=HEADERS).json()["connected"] is False
    response = login(api)
    assert response.status_code == 200
    assert response.json()["connected"] and response.json()["display_name"] == "Synthetic Runner"
    assert PASSWORD not in response.text
    assert api.get("/garmin/status", headers=HEADERS).json()["expires_at"] > time.time()
    assert fake_garmin["login"] == 1 and fake_garmin["refresh"] == 0
    assert fake_garmin["client"].last_resp.request.body is None
    directory = tmp_path / "tokens"
    assert directory.stat().st_mode & 0o777 == 0o700
    for path in directory.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
        assert PASSWORD not in path.read_text()
    assert not (tmp_path / "coach.db").exists()
    assert PASSWORD not in caplog.text
    assert api.post("/garmin/logout", headers=HEADERS).json()["connected"] is False
    state = json.loads((directory / "connection.tokens.json").read_text())
    assert "tokens" not in state
    assert api.get("/garmin/status", headers=HEADERS).json()["connected"] is False


def test_mfa_resumes_once_without_password(api, fake_garmin, tmp_path):
    result = login(api, "mfa@example.test").json()
    assert result["mfa_required"] and not result["connected"]
    assert not (tmp_path / "tokens" / "connection.tokens.json").exists()
    response = api.post(
        "/garmin/mfa",
        json={"challenge_id": result["challenge_id"], "code": "123456"},
        headers=HEADERS,
    )
    assert response.status_code == 200 and response.json()["connected"]
    assert fake_garmin["login"] == fake_garmin["mfa"] == 1
    assert (
        api.post(
            "/garmin/mfa",
            json={"challenge_id": result["challenge_id"], "code": "123456"},
            headers=HEADERS,
        ).status_code
        == 502
    )
    assert fake_garmin["mfa"] == 1


def test_failed_login_and_validation_never_echo_secrets(api, fake_garmin, caplog, tmp_path):
    caplog.set_level(logging.DEBUG)
    response = login(api, "wrong@example.test")
    assert response.status_code == 502 and PASSWORD not in response.text
    for body in (
        {"email": "", "password": PASSWORD},
        {"password": [PASSWORD]},
        {"email": "x", "password": PASSWORD, "extra": PASSWORD},
    ):
        response = api.post("/garmin/login", json=body, headers=HEADERS)
        assert response.status_code == 422 and PASSWORD not in response.text
    response = api.post(
        "/garmin/login",
        content='{"password": "' + PASSWORD,
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    assert response.status_code == 422 and PASSWORD not in response.text
    assert fake_garmin["login"] == 1 and PASSWORD not in caplog.text
    assert not (tmp_path / "tokens" / "connection.tokens.json").exists()


def test_auth_required_for_all_connection_routes(api, fake_garmin):
    for method, path in [("post", "login"), ("post", "mfa"), ("post", "logout"), ("get", "status")]:
        assert getattr(api, method)("/garmin/" + path).status_code == 401
    assert fake_garmin["login"] == 0


def expire(vault, expiry):
    with vault.locked():
        state = vault.read()
        client = Client()
        client.oauth1_token, client.oauth2_token = tokens(expiry)
        vault.write({**state, "tokens": client.dumps()})


@pytest.mark.parametrize("offset", [-1, 30])
def test_renew_expired_or_near_expiry_once_and_persist(tmp_path, fake_garmin, offset):
    connection = GarminConnection(tmp_path / "tokens")
    connection.login("runner@example.test", PASSWORD)
    expire(connection.vault, int(time.time()) + offset)
    client = GarminClient(tmp_path / "tokens")
    assert client.api.garth.oauth2_token.expires_at > time.time() + 60
    assert fake_garmin["refresh"] == 1
    with pytest.raises(GarminError, match="Reconnect Garmin"):
        client.api.garth.refresh_oauth2()
    assert fake_garmin["refresh"] == 1
    assert connection.status().connected
    assert fake_garmin["refresh"] == 1 and fake_garmin["login"] == 1


def test_failed_renewal_has_no_login_or_retry(tmp_path, fake_garmin, monkeypatch):
    connection = GarminConnection(tmp_path / "tokens")
    connection.login("runner@example.test", PASSWORD)
    expire(connection.vault, int(time.time()) - 1)
    calls = []

    def fail(*args):
        calls.append(1)
        raise RuntimeError(PASSWORD)

    monkeypatch.setattr(sso, "exchange", fail)
    with pytest.raises(GarminError, match="Reconnect Garmin") as error:
        GarminClient(tmp_path / "tokens")
    assert PASSWORD not in str(error.value)
    assert len(calls) == 1 and fake_garmin["login"] == 1


def test_disconnect_invalidates_pending_mfa_and_old_session(tmp_path, fake_garmin):
    connection = GarminConnection(tmp_path / "tokens")
    connection.login("runner@example.test", PASSWORD)
    old = StoredSession(connection.vault)
    pending = connection.login("mfa@example.test", PASSWORD)
    GarminConnection(tmp_path / "tokens").logout()
    with pytest.raises(GarminError, match="changed"):
        connection.complete(pending.challenge_id, "123456")
    with pytest.raises(GarminError, match="Reconnect Garmin"):
        old.refresh_oauth2()
    assert not connection.status().connected
    assert fake_garmin["mfa"] == fake_garmin["refresh"] == 0


def test_mfa_failure_expiry_and_replacement(api, fake_garmin, monkeypatch):
    first = login(api, "mfa@example.test").json()
    second = login(api, "mfa@example.test").json()
    assert first["challenge_id"] != second["challenge_id"]
    assert (
        api.post(
            "/garmin/mfa",
            json={"challenge_id": first["challenge_id"], "code": "123456"},
            headers=HEADERS,
        ).status_code
        == 502
    )
    response = api.post(
        "/garmin/mfa",
        json={"challenge_id": second["challenge_id"], "code": "wrong"},
        headers=HEADERS,
    )
    assert response.status_code == 502 and PASSWORD not in response.text
    third = login(api, "mfa@example.test").json()
    monkeypatch.setattr("stride_coach.garmin_auth.time.monotonic", lambda: float("inf"))
    assert (
        api.post(
            "/garmin/mfa",
            json={"challenge_id": third["challenge_id"], "code": "123456"},
            headers=HEADERS,
        ).status_code
        == 502
    )
    assert fake_garmin["mfa"] == 1


def test_unowned_or_symlink_store_is_untouched(tmp_path, fake_garmin):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "oauth1_token.json").write_text("other-tool-token")
    before = shared.stat().st_mode
    for operation in ("status", "logout"):
        with pytest.raises(GarminError, match="not owned"):
            getattr(GarminConnection(shared), operation)()
    assert shared.stat().st_mode == before
    assert (shared / "oauth1_token.json").read_text() == "other-tool-token"
    link = tmp_path / "link"
    link.symlink_to(shared)
    with pytest.raises(GarminError, match="dedicated"):
        GarminConnection(link).login("runner@example.test", PASSWORD)
    assert fake_garmin["login"] == 0


def test_cli_interactive_login_mfa_status_logout(tmp_path, fake_garmin):
    runner = CliRunner()
    base = ["--tokens", str(tmp_path / "tokens"), "garmin"]
    result = runner.invoke(app, [*base, "login"], input=f"mfa@example.test\n{PASSWORD}\n123456\n")
    assert result.exit_code == 0, result.output
    assert PASSWORD not in result.output and '"connected": true' in result.output
    assert '"connected": true' in runner.invoke(app, [*base, "status"]).output
    assert '"connected": false' in runner.invoke(app, [*base, "logout"]).output
    assert '"connected": false' in runner.invoke(app, [*base, "status"]).output


def test_corrupt_store_and_profile_outage(tmp_path, fake_garmin, monkeypatch):
    monkeypatch.setattr(
        Client, "user_profile", property(lambda self: (_ for _ in ()).throw(RuntimeError(PASSWORD)))
    )
    connection = GarminConnection(tmp_path / "tokens")
    assert connection.login("runner@example.test", PASSWORD).display_name is None
    with connection.vault.locked():
        connection.vault.write({"tokens": "invalid"})
    with pytest.raises(GarminError, match="Reconnect Garmin"):
        connection.status()


def test_password_validation_is_sanitized_behind_proxy_prefix(tmp_path, fake_garmin):
    config = ServerConfig(token="synthetic-bearer-" * 3, tokens=tmp_path / "tokens")
    with TestClient(create_app(config), root_path="/coach") as client:
        response = client.post(
            "/coach/garmin/login", json={"password": [PASSWORD]}, headers=HEADERS
        )
        assert response.status_code == 422
        assert PASSWORD not in response.text
    assert fake_garmin["login"] == 0
