"""Shared application operations for CLI, MCP, and HTTP transports."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from .activity_capture import capture_pending
from .activity_models import BackfillResult
from .activity_storage import read_detail, read_streams
from .adaptation import adapt as adapt_week
from .adaptation import propose, week_metrics
from .engine import generate_plan
from .garmin import GarminClient
from .garmin import push as push_workouts
from .garmin import remove as remove_workouts
from .garmin_auth import DEFAULT_TOKENS as DEFAULT_TOKENS
from .models import Activity, Adjustment, Fitness, Plan, Record, Setup, Workout
from .storage import Store
from .sync_models import SyncAttempt, SyncStatus


class Match(Record):
    workout_id: str
    activity_id: str
    method: str


class Metrics(Record):
    week: int
    planned_sessions: int
    matched_sessions: int
    compliance: float
    planned_minutes: float
    completed_minutes: float
    trimp: float
    missing_hr: int
    matches: list[Match]


class Load(Record):
    week: int
    trimp: float
    missing_hr: int
    completed_minutes: float


class WorkoutView(Record):
    workout: Workout
    minutes: float


class WeekView(Record):
    workouts: list[WorkoutView]
    metrics: Metrics


class Created(Record):
    plan_id: str
    sessions: int
    fitness: Fitness
    warnings: list[str]


class SyncResult(Record):
    details: BackfillResult | None = None
    synced: int
    since: date
    until: date
    source: str


class SyncWindow(Record):
    since: date
    until: date


class Status(Record):
    plan_id: str
    sync: SyncWindow | None
    scheduled_workouts: int
    weeks: list[Metrics]
    adjustments: list[Adjustment]
    sync_status: SyncStatus | None = None


class Proposal(Record):
    preview_only: bool = True
    requires_closed_week_and_sync: bool = True
    adjustment: Adjustment


class WriteResult(Record):
    action: str
    date: str | None = None
    payload: dict | None = None
    workout_id: str | None = None
    remote_id: str | None = None
    ownership_tag: str | None = None


class GoalRequest(Record):
    setup: Setup
    recent_runs: list[Activity] | None = None


class PushRequest(Record):
    week: int | None = Field(default=None, ge=1)
    workout: str | None = None
    apply: bool = False
    dry_run: bool = False


class SyncRequest(Record):
    since: date | None = None
    until: date | None = None
    activities: list[Activity] | None = None


class AdaptRequest(Record):
    week: int = Field(ge=2)
    apply: bool = False
    proposal_fingerprint: str | None = None


class RemoveRequest(Record):
    apply: bool = False
    dry_run: bool = False


class Coach:
    def __init__(self, store: Store, token_dir: Path = DEFAULT_TOKENS, client_factory=GarminClient):
        self.store = store
        self.token_dir = token_dir
        self.client_factory = client_factory

    def initialize(self, request: GoalRequest) -> Created:
        runs = request.recent_runs if request.recent_runs is not None else self.store.activities()
        plan = generate_plan(request.setup, runs)
        with self.store.lock():
            self.store.initialize(plan)
        return Created(
            plan_id=plan.id,
            sessions=len(plan.workouts),
            fitness=plan.fitness,
            warnings=plan.warnings,
        )

    def plan(self) -> Plan:
        return self.store.plan()

    def week(self, number: int) -> WeekView:
        plan = self.plan()
        if number not in {w.week for w in plan.workouts}:
            raise ValueError("Week is outside this plan")
        return WeekView(
            workouts=[
                WorkoutView(workout=w, minutes=w.minutes) for w in plan.workouts if w.week == number
            ],
            metrics=Metrics(**week_metrics(plan, self.store.activities(), number)),
        )

    def compliance(self) -> list[Metrics]:
        plan, activities = self.plan(), self.store.activities()
        return [
            Metrics(**week_metrics(plan, activities, n))
            for n in sorted({w.week for w in plan.workouts})
        ]

    def load(self) -> list[Load]:
        return [
            Load(
                week=m.week,
                trimp=m.trimp,
                missing_hr=m.missing_hr,
                completed_minutes=m.completed_minutes,
            )
            for m in self.compliance()
        ]

    def status(self) -> Status:
        store = self.store
        window = store.sync_window()
        return Status(
            plan_id=self.plan().id,
            sync=SyncWindow(**window) if window else None,
            scheduled_workouts=store.scheduled_count(),
            weeks=self.compliance(),
            adjustments=store.adjustments(),
            sync_status=store.sync_status(),
        )

    def push(self, request: PushRequest, today: date | None = None) -> list[WriteResult]:
        if request.apply and request.dry_run:
            raise ValueError("Choose apply or dry_run, not both")
        today = today or date.today()
        selected = [
            w
            for w in self.plan().workouts
            if (request.week is None or w.week == request.week)
            and (request.workout is None or w.id == request.workout)
            and w.day >= today
        ]
        if not selected:
            raise ValueError("No future workouts match this selection")
        client = self.client_factory(self.token_dir) if request.apply else None
        return [
            WriteResult(**r)
            for r in push_workouts(self.store, selected, client, dry_run=not request.apply)
        ]

    def remove(self, request: RemoveRequest) -> list[WriteResult]:
        if request.apply and request.dry_run:
            raise ValueError("Choose apply or dry_run, not both")
        self.plan()
        client = self.client_factory(self.token_dir) if request.apply else None
        return [
            WriteResult(**r) for r in remove_workouts(self.store, client, dry_run=not request.apply)
        ]

    def sync(
        self, request: SyncRequest, today: date | None = None, *, source="manual", now=None
    ) -> SyncResult:
        today = today or date.today()
        end = request.until or today
        begin = request.since or self.plan().setup.start - timedelta(days=28)
        if begin > end or end > today:
            raise ValueError("Sync needs since <= until <= today")
        with self.store.lock():
            attempt = SyncAttempt(
                id=uuid4().hex,
                source=source,
                started_at=now or datetime.now(UTC),
                since=begin,
                until=end,
            )
            self.store.save_attempt(attempt)
            try:
                client = self.client_factory(self.token_dir) if request.activities is None else None
                runs = (
                    request.activities
                    if request.activities is not None
                    else client.activities(begin, end)
                )
                runs = [a for a in runs if begin <= a.day <= end]
                if request.activities is not None:
                    runs = [a.model_copy(update={"source": "local"}) for a in runs]
                self.store.save_sync(runs, begin.isoformat(), end.isoformat(), today=today)
                attempt.result = "success"
                attempt.activity_count = len(runs)
            except Exception:
                attempt.result = "error"
                attempt.error = "Sync failed. Check connectivity or reconnect Garmin, then retry."
                raise
            finally:
                attempt.finished_at = datetime.now(UTC)
                self.store.save_attempt(attempt)
        details = (
            capture_pending(self.store, client)
            if client and hasattr(client, "activity_detail")
            else None
        )
        return SyncResult(
            details=details,
            synced=len(runs),
            since=begin,
            until=end,
            source="local import" if request.activities is not None else "Garmin",
        )

    def activity(self, activity_id: str):
        return read_detail(self.store, activity_id)

    def activity_streams(self, activity_id: str):
        return read_streams(self.store, activity_id)

    def backfill_details(self, limit: int = 20, include_legacy: bool = False):
        return capture_pending(
            self.store,
            self.client_factory(self.token_dir),
            limit=limit,
            include_legacy=include_legacy,
        )

    def adapt(self, request: AdaptRequest, today: date | None = None) -> Adjustment:
        return adapt_week(
            self.store,
            request.week,
            today or date.today(),
            request.apply,
            request.proposal_fingerprint,
        )

    def propose_adjustment(self, number: int) -> Proposal:
        with self.store.lock():
            return Proposal(adjustment=propose(self.plan(), self.store.activities(), number))


def read_activities(path: Path) -> list[Activity]:
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("Activities file must contain a JSON array")
    return [Activity.model_validate(a) for a in data]
