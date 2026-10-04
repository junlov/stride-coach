"""Single-account Garmin connection. Passwords never enter persisted state."""

import json
import os
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from garth.http import Client
from pydantic import Field, SecretStr

from .database import TOKEN_LOCK, advisory_lock
from .models import Record

DEFAULT_TOKENS = Path("~/.local/share/stride-coach/garmin")
AUTH_ERROR = "Connect Garmin in Settings or run stride-coach garmin login."
RECONNECT_ERROR = "Garmin session renewal failed. Reconnect Garmin in Settings or the CLI."


class GarminError(RuntimeError):
    pass


class GarminLogin(Record):
    email: str = Field(min_length=1, max_length=320, repr=False)
    password: SecretStr = Field(min_length=1, max_length=4096)


class GarminMFA(Record):
    challenge_id: str = Field(min_length=1, max_length=128)
    code: SecretStr = Field(min_length=1, max_length=32)


class GarminStatus(Record):
    connected: bool
    display_name: str | None = None
    expires_at: int | None = None


class GarminLoginResult(GarminStatus):
    mfa_required: bool = False
    challenge_id: str | None = None


class TokenVault:
    """Claim only empty directories; never adopt another tool's token store."""

    def __init__(self, path: Path, database_url: str | None = None):
        self.path = path.expanduser()
        self.database_url = database_url

    @contextmanager
    def locked(self):
        with advisory_lock(TOKEN_LOCK, self.database_url):
            with self._directory():
                yield self

    @contextmanager
    def _directory(self):
        path = self.path
        if path.is_symlink() or path.resolve() in {
            Path("~/.garminconnect").expanduser().resolve(),
            Path("~/.garth").expanduser().resolve(),
        }:
            raise GarminError("Use a dedicated stride-coach token directory, not a shared store.")
        marker = path / ".stride-coach"
        if path.exists() and not marker.is_file() and any(path.iterdir()):
            raise GarminError(
                "Token directory is not owned by stride-coach. Choose an empty directory."
            )
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name in (".stride-coach", ".lock", "connection.tokens.json"):
            if (path / name).is_symlink():
                raise GarminError("Token store must not contain symbolic links.")
        path.chmod(0o700)
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT, 0o600)
        os.close(fd)
        yield self

    def read(self):
        file = self.path / "connection.tokens.json"
        return json.loads(file.read_text()) if file.exists() else {}

    def write(self, state):
        fd, name = tempfile.mkstemp(prefix=".connection-", suffix=".tokens.json", dir=self.path)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump(state, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, self.path / "connection.tokens.json")
        finally:
            if os.path.exists(name):
                os.unlink(name)


def scrub_requests(client):
    """Requests retains submitted forms on Response.request, including during MFA."""
    response = getattr(client, "last_resp", None)
    if response is not None:
        for item in [response, *response.history]:
            if item.request is not None:
                item.request.body = None


class GarminConnection:
    """One pending MFA challenge per server process, expiring after five minutes."""

    def __init__(self, token_dir: Path, database_url: str | None = None):
        self.vault = TokenVault(token_dir, database_url)
        self.lock = threading.Lock()
        self.pending = None
        self.timer = None

    def _clear(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        if self.pending:
            self.pending[2].sess.close()
        self.pending = None

    def _expire(self, challenge=None):
        with self.lock:
            if challenge is None or (self.pending and self.pending[0] == challenge):
                self._clear()

    def close(self):
        """Discard pending MFA and close its HTTP session at process shutdown."""
        self._expire()

    def login(self, email: str, password: str) -> GarminLoginResult:
        from garth import sso

        with self.lock:
            self._clear()
            client = Client()
            client.configure(retries=0)
            try:
                with self.vault.locked():
                    generation = self.vault.read().get("generation")
                # Exactly one password call, with transport retries disabled.
                result = sso.login(email, password, client=client, return_on_mfa=True)
                if result[0] == "needs_mfa":
                    challenge = secrets.token_urlsafe(32)
                    self.pending = (
                        challenge,
                        time.monotonic() + 300,
                        client,
                        result[1],
                        generation,
                    )
                    self.timer = threading.Timer(300, self._expire, args=(challenge,))
                    self.timer.daemon = True
                    self.timer.start()
                    return GarminLoginResult(
                        connected=False, mfa_required=True, challenge_id=challenge
                    )
                client.oauth1_token, client.oauth2_token = result
                return self._finish(client, generation)
            except GarminError:
                raise
            except Exception:
                raise GarminError(
                    "Garmin login failed. Check your details before trying again."
                ) from None
            finally:
                scrub_requests(client)
                if self.pending is None:
                    client.sess.close()

    def complete(self, challenge: str, code: str) -> GarminLoginResult:
        from garth import sso

        with self.lock:
            pending = self.pending
            if not pending or not secrets.compare_digest(challenge, pending[0]):
                raise GarminError("MFA challenge is unavailable. Connect Garmin again.")
            _, deadline, client, state, generation = pending
            try:
                if time.monotonic() >= deadline:
                    raise GarminError("MFA challenge expired. Connect Garmin again.")
                with self.vault.locked():
                    if self.vault.read().get("generation") != generation:
                        raise GarminError("Garmin connection changed. Connect Garmin again.")
                client.oauth1_token, client.oauth2_token = sso.resume_login(state, code)
                return self._finish(client, generation)
            except GarminError:
                raise
            except Exception:
                raise GarminError("Garmin MFA failed. Connect Garmin again when ready.") from None
            finally:
                scrub_requests(client)
                self._clear()

    def _finish(self, client, generation):
        if not client.oauth1_token or not client.oauth2_token or client.oauth2_token.expired:
            raise GarminError("Garmin login did not return a valid session. Connect Garmin again.")
        name = None
        try:
            profile = client.user_profile
            name = profile.get("fullName") or profile.get("displayName")
        except Exception:
            pass  # A profile outage must not repeat the password login.
        with self.vault.locked():
            if self.vault.read().get("generation") != generation:
                raise GarminError("Garmin connection changed. Connect Garmin again.")
            self.vault.write(
                {
                    "generation": secrets.token_hex(16),
                    "tokens": client.dumps(),
                    "display_name": name,
                }
            )
        return GarminLoginResult(
            connected=True, display_name=name, expires_at=client.oauth2_token.expires_at
        )

    def status(self) -> GarminStatus:
        try:
            with self.vault.locked():
                state = self.vault.read()
                if not state.get("tokens"):
                    return GarminStatus(connected=False)
                client = StoredSession(self.vault, state)
                try:
                    return GarminStatus(
                        connected=True,
                        display_name=state.get("display_name"),
                        expires_at=client.oauth2_token.expires_at,
                    )
                finally:
                    client.sess.close()
        except GarminError:
            raise
        except Exception:
            raise GarminError(RECONNECT_ERROR) from None

    def logout(self) -> GarminStatus:
        with self.lock:
            self._clear()
            with self.vault.locked():
                # A non-secret tombstone invalidates pending MFA in other processes.
                self.vault.write({"generation": secrets.token_hex(16)})
        return GarminStatus(connected=False)


class StoredSession(Client):
    """One renewal budget per application request, including garth's implicit refresh."""

    def __init__(self, vault: TokenVault, state=None):
        super().__init__()
        self.configure(retries=0)
        self.vault = vault
        self.renewed = False
        if state is None:
            with vault.locked():
                self._load(vault.read())
                self._ensure_locked()
        else:
            self._load(state)
            self._ensure_locked()

    def _load(self, state):
        if not state.get("tokens"):
            raise GarminError(AUTH_ERROR)
        self.generation = state.get("generation")
        try:
            self.loads(state["tokens"])
        except Exception:
            raise GarminError(RECONNECT_ERROR) from None

    def _ensure_locked(self):
        if self.oauth2_token.expires_at <= time.time() + 60:
            self._renew_locked()

    def _renew_locked(self):
        if self.renewed:
            raise GarminError(RECONNECT_ERROR)
        self.renewed = True
        try:
            state = self.vault.read()
            if state.get("generation") != self.generation or not state.get("tokens"):
                raise GarminError(AUTH_ERROR)
            super().refresh_oauth2()
            if self.oauth2_token.expired:
                raise GarminError(RECONNECT_ERROR)
            self.vault.write({**state, "tokens": self.dumps()})
        except Exception:
            raise GarminError(RECONNECT_ERROR) from None

    def refresh_oauth2(self):
        with self.vault.locked():
            self._renew_locked()
