"""Short-lived pairing credentials. Persist hashes only; consume atomically."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from pydantic import Field, SecretStr
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert

from .database import make_engine
from .db_models import PairingCodeRow, PairingLimitRow
from .models import Record

PAIRING_SECONDS = 600
ATTEMPTS_PER_MINUTE = 20


class PairingCode(Record):
    code: str = Field(pattern=r"^[A-F0-9]{24}$", repr=False)
    expires_in: int = PAIRING_SECONDS


class PairingExchange(Record):
    code: SecretStr = Field(min_length=1, max_length=128)


class PairedToken(Record):
    token: str = Field(repr=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def server_url(value: str) -> str:
    """HTTPS for phones, with the same local-development exceptions as the app."""
    try:
        url = urlsplit(value.strip())
        local = url.hostname in {"localhost", "127.0.0.1", "::1", "10.0.2.2"}
        if (
            not url.hostname
            or (url.scheme != "https" and not (url.scheme == "http" and local))
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or any(char.isspace() for char in value)
        ):
            raise ValueError
        _ = url.port
    except ValueError:
        raise ValueError(
            "Use an HTTPS server URL without credentials, query, or fragment."
        ) from None
    return value.strip().rstrip("/")


class PairingStore:
    def __init__(self, url: str, token: str):
        self.engine = make_engine(url)
        self.token_hash = digest(token)

    def close(self):
        self.engine.dispose()

    def issue(self) -> PairingCode:
        code = secrets.token_hex(12).upper()
        with self.engine.begin() as db:
            db.execute(delete(PairingCodeRow).where(PairingCodeRow.expires_at <= func.now()))
            db.execute(
                insert(PairingCodeRow).values(
                    code_hash=digest(code),
                    token_hash=self.token_hash,
                    expires_at=func.now() + timedelta(seconds=PAIRING_SECONDS),
                )
            )
        return PairingCode(code=code)

    def allow_attempt(self) -> bool:
        # One database-backed bucket for this single-user server. Forwarded IP headers
        # cannot bypass it, and separate workers/restarts share the same budget.
        with self.engine.begin() as db:
            db.execute(
                insert(PairingLimitRow)
                .values(id=1, window_start=datetime(1970, 1, 1, tzinfo=UTC), attempts=0)
                .on_conflict_do_nothing()
            )
            row = db.execute(select(PairingLimitRow.__table__).with_for_update()).one()
            now = db.scalar(text("SELECT clock_timestamp()"))
            reset = now >= row.window_start + timedelta(minutes=1)
            attempts = 1 if reset else min(row.attempts + 1, ATTEMPTS_PER_MINUTE + 1)
            db.execute(
                PairingLimitRow.__table__.update()
                .where(PairingLimitRow.id == 1)
                .values(window_start=now if reset else row.window_start, attempts=attempts)
            )
        return attempts <= ATTEMPTS_PER_MINUTE

    def consume(self, code: str) -> bool:
        with self.engine.begin() as db:
            # DELETE RETURNING gives exactly one winner even for concurrent exchanges.
            consumed = db.execute(
                delete(PairingCodeRow)
                .where(
                    PairingCodeRow.code_hash == digest(code.strip().upper()),
                    PairingCodeRow.token_hash == self.token_hash,
                    PairingCodeRow.expires_at > func.now(),
                )
                .returning(PairingCodeRow.code_hash)
            ).scalar_one_or_none()
        return consumed is not None
