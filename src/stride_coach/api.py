"""Authenticated single-user JSON API. No implicit Garmin writes."""

import os
import secrets
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, SecretStr, field_validator
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from .activity_models import RunStreams
from .database import check_schema, database_url, make_engine, upgrade
from .garmin import GarminClient, GarminError
from .garmin_auth import (
    GarminConnection,
    GarminLogin,
    GarminLoginResult,
    GarminMFA,
    GarminStatus,
)
from .mcp import create_server
from .models import Adjustment, Plan, Record, RunDetail
from .service import (
    DEFAULT_TOKENS,
    AdaptRequest,
    Coach,
    Created,
    GoalRequest,
    Load,
    Metrics,
    Proposal,
    PushRequest,
    RemoveRequest,
    Status,
    SyncRequest,
    SyncResult,
    WeekView,
    WriteResult,
)
from .storage import Store
from .sync_models import HistoryRequest, SyncAttempt, SyncStatus
from .sync_worker import SyncWorker


class ServerConfig(Record):
    token: SecretStr = Field(min_length=32)
    database_url: SecretStr = Field(
        default_factory=lambda: SecretStr(database_url()), validate_default=True
    )
    tokens: Path = DEFAULT_TOKENS
    timezone: str = "UTC"
    sync_enabled: bool = True
    sync_time: str = Field(default="06:00", pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    sync_open_hours: float = Field(default=6, ge=0.1, le=720)
    import_page_delay: float = Field(default=1, ge=0.1, le=60)
    cors_origins: list[str] = Field(default_factory=list)

    @field_validator("token")
    @classmethod
    def strong_token(cls, value):
        token = value.get_secret_value()
        if len(set(token)) < 8 or any(
            marker in token.lower() for marker in ("change-me", "changeme", "replace-me")
        ):
            raise ValueError("STRIDE_COACH_API_TOKEN must be a generated secret (32+ characters)")
        return value

    @field_validator("database_url")
    @classmethod
    def postgres_url(cls, value):
        url = database_url(value.get_secret_value())
        password = make_url(url).password or ""
        if (
            len(password) < 16
            or len(set(password)) < 8
            or any(marker in password.lower() for marker in ("replace-me", "change-me", "changeme"))
        ):
            raise ValueError("DATABASE_URL requires a database password of at least 16 characters")
        return SecretStr(url)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(
                "TZ must be an IANA timezone such as UTC or America/Sao_Paulo"
            ) from None
        return value

    @field_validator("cors_origins")
    @classmethod
    def exact_origins(cls, origins):
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in ("https", "http")
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or "*" in origin
            ):
                raise ValueError("CORS requires exact HTTP(S) origins without trailing slashes")
        return origins

    @classmethod
    def from_env(cls, **overrides):
        values = {
            "token": os.getenv("STRIDE_COACH_API_TOKEN", ""),
            "database_url": os.getenv("DATABASE_URL", ""),
            "tokens": os.getenv("STRIDE_COACH_TOKENS", str(DEFAULT_TOKENS)),
            "timezone": os.getenv("TZ", "UTC"),
            "sync_enabled": os.getenv("STRIDE_COACH_SYNC_ENABLED", "true"),
            "sync_time": os.getenv("STRIDE_COACH_SYNC_TIME", "06:00"),
            "sync_open_hours": os.getenv("STRIDE_COACH_SYNC_OPEN_HOURS", "6"),
            "import_page_delay": os.getenv("STRIDE_COACH_IMPORT_PAGE_DELAY", "1"),
            "cors_origins": [
                v.strip()
                for v in os.getenv("STRIDE_COACH_CORS_ORIGINS", "").split(",")
                if v.strip()
            ],
        }
        return cls(**{**values, **overrides})


class Error(Record):
    detail: str


def create_app(config: ServerConfig, client_factory=GarminClient) -> FastAPI:
    url = config.database_url.get_secret_value()
    mcp = create_server(url, timezone=config.timezone, remote_http=True)
    mcp_app = mcp.streamable_http_app()
    connection = GarminConnection(config.tokens, database_url=url)
    if client_factory is GarminClient:
        from functools import partial

        client_factory = partial(GarminClient, database_url=url)

    worker = SyncWorker(config, connection, client_factory)

    @asynccontextmanager
    async def lifespan(app):
        try:
            upgrade(url)
            # Validate the dedicated session directory before serving traffic.
            with connection.vault.locked():
                pass
            worker.start()
            async with mcp.session_manager.run():
                yield
        except SQLAlchemyError:
            raise RuntimeError(
                "Database startup failed. Check DATABASE_URL and PostgreSQL."
            ) from None
        finally:
            worker.close()
            connection.close()

    app = FastAPI(
        lifespan=lifespan,
        title="stride-coach",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        description="Single-user running coach. Bearer authentication is required. "
        "Garmin push/removal default to previews; only apply=true permits writes.",
    )
    app.state.garmin_connection = connection
    app.state.sync_worker = worker
    bearer = HTTPBearer(auto_error=False, scheme_name="CoachBearer")

    def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)]):
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not secrets.compare_digest(
                credentials.credentials.encode(), config.token.get_secret_value().encode()
            )
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def coach(_: Annotated[None, Depends(authenticate)]) -> Iterator[Coach]:
        store = Store(url, migrate=False)
        try:
            yield Coach(store, config.tokens, client_factory)
        finally:
            store.close()

    @app.middleware("http")
    async def protect_mcp(request: Request, call_next):
        # Mounted ASGI applications do not inherit FastAPI route dependencies.
        # Protect every method, including the slash redirect, before dispatch.
        if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
            try:
                authenticate(await bearer(request))
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                    headers=exc.headers,
                )
            origin = request.headers.get("origin")
            if origin is not None and origin not in config.cors_origins:
                return JSONResponse(status_code=403, content={"detail": "Invalid Origin"})
        return await call_next(request)

    app.mount("/mcp", mcp_app)

    Service = Annotated[Coach, Depends(coach)]
    errors = {400: {"model": Error}, 401: {"model": Error}, 502: {"model": Error}}

    @app.exception_handler(SQLAlchemyError)
    async def database_failed(request: Request, exc: SQLAlchemyError):
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

    @app.get("/health", include_in_schema=False)
    def health():
        engine = make_engine(url)
        try:
            with engine.connect() as db:
                db.execute(text("SELECT 1"))
                check_schema(db)
            return {"status": "ready"}
        except (SQLAlchemyError, ValueError):
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        finally:
            engine.dispose()

    @app.exception_handler(ValueError)
    async def invalid_request(request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(GarminError)
    async def garmin_failed(request: Request, exc: GarminError):
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def invalid_body(request: Request, exc: RequestValidationError):
        # Garmin inputs can contain passwords, including in malformed JSON and extra fields.
        if getattr(request.scope.get("route"), "path", "").startswith("/garmin/"):
            return JSONResponse(status_code=422, content={"detail": "Invalid request fields."})
        return await request_validation_exception_handler(request, exc)

    @app.post(
        "/garmin/login",
        response_model=GarminLoginResult,
        responses={**errors, 422: {"model": Error, "description": "Unprocessable Content"}},
        operation_id="garmin_login",
        dependencies=[Depends(authenticate)],
    )
    def garmin_login(body: GarminLogin):
        return connection.login(body.email, body.password.get_secret_value())

    @app.post(
        "/garmin/mfa",
        response_model=GarminLoginResult,
        responses={**errors, 422: {"model": Error, "description": "Unprocessable Content"}},
        operation_id="garmin_mfa",
        dependencies=[Depends(authenticate)],
    )
    def garmin_mfa(body: GarminMFA):
        return connection.complete(body.challenge_id, body.code.get_secret_value())

    @app.get(
        "/garmin/status",
        response_model=GarminStatus,
        responses={**errors, 422: {"model": Error, "description": "Unprocessable Content"}},
        operation_id="garmin_status",
        dependencies=[Depends(authenticate)],
    )
    def garmin_status():
        return connection.status()

    @app.post(
        "/garmin/logout",
        response_model=GarminStatus,
        responses={**errors, 422: {"model": Error, "description": "Unprocessable Content"}},
        operation_id="garmin_logout",
        dependencies=[Depends(authenticate)],
    )
    def garmin_logout():
        return connection.logout()

    @app.get("/openapi.json", include_in_schema=False, dependencies=[Depends(authenticate)])
    def openapi_schema():
        return app.openapi()

    @app.post("/goal", response_model=Created, responses=errors, operation_id="setup_goal")
    def setup_goal(body: GoalRequest, service: Service):
        return service.initialize(body)

    @app.get("/plan", response_model=Plan, responses=errors, operation_id="get_plan")
    def plan(service: Service):
        return service.plan()

    @app.get("/weeks/{number}", response_model=WeekView, responses=errors, operation_id="get_week")
    def week(number: int, service: Service):
        return service.week(number)

    @app.get("/status", response_model=Status, responses=errors, operation_id="get_status")
    def status(service: Service):
        return service.status()

    @app.get(
        "/compliance", response_model=list[Metrics], responses=errors, operation_id="get_compliance"
    )
    def compliance(service: Service):
        return service.compliance()

    @app.get("/load", response_model=list[Load], responses=errors, operation_id="get_load")
    def load(service: Service):
        return service.load()

    @app.post("/push", response_model=list[WriteResult], responses=errors, operation_id="push_plan")
    def push(body: PushRequest, service: Service):
        return service.push(body)

    @app.post("/sync", response_model=SyncResult, responses=errors, operation_id="sync_activities")
    def sync(body: SyncRequest, service: Service):
        return service.sync(body)

    @app.get(
        "/sync/status", response_model=SyncStatus, responses=errors, operation_id="get_sync_status"
    )
    def sync_status(service: Service):
        return service.store.sync_status()

    @app.post(
        "/sync/open", response_model=SyncStatus, responses=errors, operation_id="sync_on_open"
    )
    def sync_on_open(service: Service):
        return worker.automatic(service.store, "app-open", worker.now())

    @app.post(
        "/sync/history", response_model=SyncAttempt, responses=errors, operation_id="import_history"
    )
    def import_history(body: HistoryRequest, service: Service):
        return worker.enqueue(service.store, body)

    @app.get(
        "/activities/{activity_id}",
        response_model=RunDetail,
        responses=errors,
        operation_id="get_activity",
    )
    def activity(activity_id: str, service: Service):
        return service.activity(activity_id)

    @app.get(
        "/activities/{activity_id}/streams",
        response_model=RunStreams | None,
        responses=errors,
        operation_id="get_activity_streams",
    )
    def activity_streams(activity_id: str, service: Service):
        return service.activity_streams(activity_id)

    @app.post("/adapt", response_model=Adjustment, responses=errors, operation_id="adapt_week")
    def adapt(body: AdaptRequest, service: Service):
        return service.adapt(body)

    @app.post(
        "/adjustments/propose/{number}",
        response_model=Proposal,
        responses=errors,
        operation_id="propose_adjustment",
    )
    def propose_adjustment(number: int, service: Service):
        return service.propose_adjustment(number)

    @app.post(
        "/remove",
        response_model=list[WriteResult],
        responses=errors,
        operation_id="remove_owned_workouts",
    )
    def remove(body: RemoveRequest, service: Service):
        return service.remove(body)

    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type", "MCP-Protocol-Version"],
            allow_credentials=False,
        )
    return app
