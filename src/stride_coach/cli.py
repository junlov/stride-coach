"""CLI transport. Application behavior belongs to service.Coach."""

import json
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel

from .garmin import GarminError
from .models import Athlete, Goal, Setup
from .service import (
    DEFAULT_DB,
    DEFAULT_TOKENS,
    AdaptRequest,
    Coach,
    GoalRequest,
    PushRequest,
    RemoveRequest,
    SyncRequest,
    read_activities,
)
from .storage import Store

app = typer.Typer(no_args_is_help=True, help="Local running plans and explicit Garmin commands.")


def emit(data):
    def encode(value):
        return (
            value.model_dump(mode="json", exclude_none=True)
            if isinstance(value, BaseModel)
            else str(value)
        )

    typer.echo(json.dumps(data, indent=2, default=encode))


@app.callback()
def options(
    ctx: typer.Context,
    db: Annotated[Path, typer.Option(envvar="STRIDE_COACH_DB")] = DEFAULT_DB,
    tokens: Annotated[Path, typer.Option(envvar="STRIDE_COACH_TOKENS")] = DEFAULT_TOKENS,
):
    ctx.obj = {"db": db.expanduser(), "tokens": tokens.expanduser()}


@contextmanager
def session(ctx):
    store = None
    try:
        store = Store(ctx.obj["db"])
        yield Coach(store, ctx.obj["tokens"])
    except (ValueError, OSError, GarminError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None
    finally:
        if store:
            store.close()


@app.command()
def init(
    ctx: typer.Context,
    goal: Goal,
    race_date: str,
    days: Annotated[int, typer.Option(min=2, max=6)] = 3,
    long_run_day: Annotated[int, typer.Option(min=0, max=6)] = 6,
    start: str | None = None,
    recent_runs: Path | None = None,
    resting_hr: int = 60,
    max_hr: int = 190,
    trimp_a: float = 0.64,
    trimp_b: float = 1.92,
):
    """Create a plan; long-run-day is Monday=0 through Sunday=6."""
    with session(ctx) as coach:
        today = date.today()
        monday = today + timedelta(days=(-today.weekday()) % 7)
        setup = Setup(
            goal=goal,
            race_date=date.fromisoformat(race_date),
            start=date.fromisoformat(start) if start else monday,
            days_per_week=days,
            long_run_day=long_run_day,
            athlete=Athlete(resting_hr=resting_hr, max_hr=max_hr, trimp_a=trimp_a, trimp_b=trimp_b),
        )
        emit(
            coach.initialize(
                GoalRequest(
                    setup=setup, recent_runs=read_activities(recent_runs) if recent_runs else None
                )
            )
        )


@app.command()
def plan(ctx: typer.Context, week: int | None = None):
    """Show the plan with durations and pace/HR targets."""
    with session(ctx) as coach:
        if week is not None:
            emit(coach.week(week))
        else:
            emit(coach.plan())


@app.command()
def push(
    ctx: typer.Context,
    week: int | None = None,
    workout: str | None = None,
    apply: bool = False,
    dry_run: bool = False,
):
    """Preview payloads by default. --apply explicitly uploads and schedules."""
    with session(ctx) as coach:
        emit(coach.push(PushRequest(week=week, workout=workout, apply=apply, dry_run=dry_run)))


@app.command()
def remove(ctx: typer.Context, apply: bool = False, dry_run: bool = False):
    """Remove only workouts bearing this plan's exact ownership tags."""
    with session(ctx) as coach:
        emit(coach.remove(RemoveRequest(apply=apply, dry_run=dry_run)))


@app.command()
def sync(
    ctx: typer.Context,
    since: str | None = None,
    until: str | None = None,
    activities: Path | None = None,
):
    """Pull running activities, or import normalized JSON for an offline workflow."""
    with session(ctx) as coach:
        emit(
            coach.sync(
                SyncRequest(
                    since=date.fromisoformat(since) if since else None,
                    until=date.fromisoformat(until) if until else None,
                    activities=read_activities(activities) if activities else None,
                )
            )
        )


@app.command()
def adapt(ctx: typer.Context, week: int, apply: bool = False):
    """Propose changes; --apply saves them locally. Run on the target Monday."""
    with session(ctx) as coach:
        emit(coach.adapt(AdaptRequest(week=week, apply=apply)))


@app.command()
def status(ctx: typer.Context):
    """Show weekly compliance, running TRIMP, sync coverage, and adjustments."""
    with session(ctx) as coach:
        emit(coach.status())


@app.command()
def serve(ctx: typer.Context, host: str = "127.0.0.1", port: int = 8000):
    """Run the single-user API. Requires STRIDE_COACH_API_TOKEN (32+ characters)."""
    import uvicorn

    from .api import ServerConfig, create_app

    try:
        config = ServerConfig.from_env(db=ctx.obj["db"], tokens=ctx.obj["tokens"])
    except ValueError:
        typer.echo(
            "Error: configure STRIDE_COACH_API_TOKEN (32+ characters) and valid CORS origins.",
            err=True,
        )
        raise typer.Exit(1) from None
    uvicorn.run(create_app(config), host=host, port=port, access_log=False)


if __name__ == "__main__":
    app()
