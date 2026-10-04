"""Real loopback HTTP proof with synthetic Garmin replies and outbound Garmin blocked."""

import argparse
import secrets
import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import uvicorn
from garth.auth_tokens import OAuth1Token, OAuth2Token
from garth.http import Client

from stride_coach.api import ServerConfig, create_app
from stride_coach.garmin_auth import TokenVault


def synthetic_tokens(expiry=None):
    return (
        OAuth1Token(oauth_token="synthetic", oauth_token_secret="synthetic"),
        OAuth2Token(
            scope="synthetic",
            jti="synthetic",
            token_type="Bearer",
            access_token="synthetic",
            refresh_token="synthetic",
            expires_in=3600,
            expires_at=expiry or int(time.time()) + 3600,
            refresh_token_expires_in=86400,
            refresh_token_expires_at=int(time.time()) + 86400,
        ),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True, type=Path)
    directory = parser.parse_args().directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    password_calls = 0
    renewals = 0

    def login(email, password, *, client, return_on_mfa):
        nonlocal password_calls
        password_calls += 1
        assert client.retries == 0 and return_on_mfa
        assert password == "synthetic-password"
        if email == "mfa@example.test":
            return "needs_mfa", {"client": client}
        return synthetic_tokens()

    def resume(state, code):
        assert code == "123456"
        return synthetic_tokens()

    def exchange(oauth1, client):
        nonlocal renewals
        renewals += 1
        return synthetic_tokens()[1]

    bearer = secrets.token_urlsafe(32)
    config = ServerConfig(token=bearer, tokens=directory / "garmin")
    application = create_app(config)
    server = uvicorn.Server(uvicorn.Config(application, log_level="error", access_log=False))
    with (
        patch("garth.sso.login", login),
        patch("garth.sso.resume_login", resume),
        patch("garth.sso.exchange", exchange),
        patch.object(
            Client, "user_profile", property(lambda self: {"fullName": "Synthetic Runner"})
        ),
        patch(
            "requests.Session.request", side_effect=AssertionError("Outbound Garmin is forbidden")
        ),
        socket.socket() as listener,
    ):
        listener.bind(("127.0.0.1", 0))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                headers={"Authorization": f"Bearer {bearer}"},
                trust_env=False,
            ) as client:
                for _ in range(100):
                    if server.started:
                        break
                    time.sleep(0.05)
                else:
                    raise RuntimeError("Loopback server did not start")
                assert (
                    client.get("/garmin/status", headers={"Authorization": "invalid"}).status_code
                    == 401
                )
                assert not client.get("/garmin/status").json()["connected"]
                print("status: HTTP 401 without bearer; HTTP 200 disconnected with bearer")
                assert client.post(
                    "/garmin/login",
                    json={"email": "runner@example.test", "password": "synthetic-password"},
                ).json()["connected"]
                print("login: HTTP 200 connected, synthetic account, one password call")
                vault = TokenVault(config.tokens)
                with vault.locked():
                    state = vault.read()
                    session = Client()
                    session.oauth1_token, session.oauth2_token = synthetic_tokens(
                        int(time.time()) - 1
                    )
                    vault.write({**state, "tokens": session.dumps()})
                assert client.get("/garmin/status").json()["expires_at"] > time.time()
                assert renewals == 1 and password_calls == 1
                print("renewal: expired token renewed once; no password login")
                challenge = client.post(
                    "/garmin/login",
                    json={"email": "mfa@example.test", "password": "synthetic-password"},
                ).json()
                assert challenge["mfa_required"]
                assert client.post(
                    "/garmin/mfa",
                    json={"challenge_id": challenge["challenge_id"], "code": "123456"},
                ).json()["connected"]
                assert password_calls == 2
                print("MFA: two HTTP requests completed with one password call")
                assert not client.post("/garmin/logout").json()["connected"]
                assert not client.get("/garmin/status").json()["connected"]
                assert "tokens" not in vault.read()
                print("disconnect: stored tokens removed; status disconnected")
                print("proof: real loopback HTTP complete; zero live Garmin calls")
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            application.state.garmin_connection.close()
            if thread.is_alive():
                raise RuntimeError("Loopback server did not stop")


if __name__ == "__main__":
    from synthetic_database import synthetic_database

    with synthetic_database():
        main()
