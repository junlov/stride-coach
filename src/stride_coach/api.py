"""Authenticated single-user JSON API. No scheduler or implicit Garmin writes."""

import os
import secrets
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, SecretStr, field_validator

from .garmin import GarminClient, GarminError
from .garmin_auth import (
    GarminConnection,
    GarminLogin,
    GarminLoginResult,
    GarminMFA,
    GarminStatus,
)
from .models import Adjustment, Plan, Record
from .service import (
    DEFAULT_DB,
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


class ServerConfig(Record):
    token: SecretStr = Field(min_length=32)
    db: Path = DEFAULT_DB
    tokens: Path = DEFAULT_TOKENS
    cors_origins: list[str] = Field(default_factory=list)

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
            "db": os.getenv("STRIDE_COACH_DB", str(DEFAULT_DB)),
            "tokens": os.getenv("STRIDE_COACH_TOKENS", str(DEFAULT_TOKENS)),
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
    connection = GarminConnection(config.tokens)

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
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
        store = Store(config.db)
        try:
            yield Coach(store, config.tokens, client_factory)
        finally:
            store.close()

    Service = Annotated[Coach, Depends(coach)]
    errors = {400: {"model": Error}, 401: {"model": Error}, 502: {"model": Error}}

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
        responses={**errors, 422: {"model": Error}},
        operation_id="garmin_login",
        dependencies=[Depends(authenticate)],
    )
    def garmin_login(body: GarminLogin):
        return connection.login(body.email, body.password.get_secret_value())

    @app.post(
        "/garmin/mfa",
        response_model=GarminLoginResult,
        responses={**errors, 422: {"model": Error}},
        operation_id="garmin_mfa",
        dependencies=[Depends(authenticate)],
    )
    def garmin_mfa(body: GarminMFA):
        return connection.complete(body.challenge_id, body.code.get_secret_value())

    @app.get(
        "/garmin/status",
        response_model=GarminStatus,
        responses={**errors, 422: {"model": Error}},
        operation_id="garmin_status",
        dependencies=[Depends(authenticate)],
    )
    def garmin_status():
        return connection.status()

    @app.post(
        "/garmin/logout",
        response_model=GarminStatus,
        responses={**errors, 422: {"model": Error}},
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
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
        )
    return app
