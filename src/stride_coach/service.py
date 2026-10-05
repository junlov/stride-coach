"""Shared application operations for CLI, MCP, and HTTP transports."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, computed_field

from .activity_capture import capture_pending
from .activity_models import BackfillResult, RunCompliance
from .activity_storage import read_detail, read_streams
from .adaptation import adapt as adapt_week
from .adaptation import propose, week_metrics
from .engine import generate_plan
from .garmin import GarminClient, GarminError, calendar_fingerprint, reconcile_calendar
from .garmin import push as push_workouts
from .garmin import remove as remove_workouts
from .garmin_auth import DEFAULT_TOKENS as DEFAULT_TOKENS
from .models import Activity, Adjustment, Fitness, Plan, Record, Setup, Workout
from .recovery import adapt_daily
from .recovery_models import DailyAdaptRequest, DailyProposal, DailyReadiness
from .storage import Store
from .sync_models import SyncAttempt, SyncStatus
from .workout_text import step_summary, workout_name


class Match(Record):
    workout_id: str
    activity_id: str
    method: str
    step_compliance: RunCompliance | None = None


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


class WorkoutSummary(Workout):
    @computed_field
    @property
    def step_descriptions(self) -> list[str]:
        return [step_summary(step) for step in self.steps]

    @computed_field
    @property
    def name(self) -> str:
        return workout_name(self)


class DailyProposalView(DailyProposal):
    before: WorkoutSummary | None = None
    after: WorkoutSummary | None = None


class PlanView(Plan):
    workouts: list[WorkoutSummary]


class WorkoutView(Record):
    workout: WorkoutSummary
    minutes: float


class WeekView(Record):
    workouts: list[WorkoutView]
    metrics: Metrics


class TodayView(Record):
    day: date
    status: Literal["workout", "rest", "outside_plan"]
    workouts: list[WorkoutView]


class CurrentWeekView(Record):
    day: date
    week: int | None
    view: WeekView | None


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
    daily_adjustments: list[DailyProposalView] = Field(default_factory=list)
    garmin_out_of_date: bool = True
    garmin_window_days: int = 14


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
    reason: str | None = None


class CalendarSettings(Record):
    window_days: int = Field(default=14, ge=7, le=28, strict=True)


class CalendarRequest(Record):
    apply: bool = False
    preview_id: str | None = None


class CalendarResult(Record):
    window_days: int
    since: date
    until: date
    preview_id: str
    applied: bool
    changes: list[WriteResult]


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
        runs = (
            request.recent_runs
            if request.recent_runs is not None
            else self.store.activities(include_cadence=True)
        )
        plan = generate_plan(request.setup, runs)
        with self.store.lock():
            self.store.initialize(plan)
        return Created(
            plan_id=plan.id,
            sessions=len(plan.workouts),
            fitness=plan.fitness,
            warnings=plan.warnings,
        )

    def plan(self) -> PlanView:
        return PlanView.model_validate(self.store.plan().model_dump())

    def week(self, number: int) -> WeekView:
        plan = self.plan()
        if number not in {w.week for w in plan.workouts}:
            raise ValueError("Week is outside this plan")
        return WeekView(
            workouts=[
                WorkoutView(workout=w, minutes=w.minutes) for w in plan.workouts if w.week == number
            ],
            metrics=self._metrics(
                plan, self.store.activities(), number, self.store.step_compliance()
            ),
        )

    @staticmethod
    def _metrics(plan, activities, number, scores):
        metrics = Metrics(**week_metrics(plan, activities, number))
        for match in metrics.matches:
            match.step_compliance = scores.get(match.activity_id)
        return metrics

    def compliance(self) -> list[Metrics]:
        plan, activities = self.plan(), self.store.activities()
        scores = self.store.step_compliance()
        return [
            self._metrics(plan, activities, n, scores)
            for n in sorted({w.week for w in plan.workouts})
        ]

    def today_workout(self, on: date | None = None) -> TodayView:
        on = on or date.today()
        plan = self.plan()
        workouts = [WorkoutView(workout=w, minutes=w.minutes) for w in plan.workouts if w.day == on]
        status = "workout" if workouts else "rest"
        if not plan.setup.start <= on < plan.setup.race_date:
            status = "outside_plan"
        return TodayView(day=on, status=status, workouts=workouts)

    def current_week(self, on: date | None = None) -> CurrentWeekView:
        on = on or date.today()
        plan = self.plan()
        number = (on - plan.setup.start).days // 7 + 1
        if not plan.setup.start <= on < plan.setup.race_date or number not in {
            w.week for w in plan.workouts
        }:
            return CurrentWeekView(day=on, week=None, view=None)
        return CurrentWeekView(day=on, week=number, view=self.week(number))

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
            daily_adjustments=[
                DailyProposalView.model_validate(proposal.model_dump())
                for proposal in store.daily_adjustments()
            ],
            garmin_window_days=store.calendar_settings()["window_days"],
            garmin_out_of_date=(
                store.calendar_settings()["synced_fingerprint"]
                != calendar_fingerprint(store, date.today())
            ),
        )

    def push(self, request: PushRequest, today: date | None = None) -> list[WriteResult]:
        if request.apply and request.dry_run:
            raise ValueError("Choose apply or dry_run, not both")
        today = today or date.today()
        end = today + timedelta(days=self.store.calendar_settings()["window_days"])
        selected = [
            w
            for w in self.plan().workouts
            if (request.week is None or w.week == request.week)
            and (request.workout is None or w.id == request.workout)
            and today <= w.day < end
        ]
        if not selected:
            raise ValueError("No future workouts match this selection")
        client = self.client_factory(self.token_dir) if request.apply else None
        return [
            WriteResult(**r)
            for r in push_workouts(self.store, selected, client, dry_run=not request.apply)
        ]

    def calendar_settings(self) -> CalendarSettings:
        return CalendarSettings(window_days=self.store.calendar_settings()["window_days"])

    def save_calendar_settings(self, request: CalendarSettings) -> CalendarSettings:
        self.store.save_calendar_settings(request.window_days)
        return self.calendar_settings()

    def calendar(self, request: CalendarRequest, today: date | None = None) -> CalendarResult:
        return CalendarResult(
            **reconcile_calendar(
                self.store,
                self.client_factory(self.token_dir),
                today or date.today(),
                apply=request.apply,
                preview_id=request.preview_id,
            )
        )

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
                if client and hasattr(client, "readiness"):
                    try:
                        readiness = DailyReadiness.model_validate(client.readiness(today))
                        if readiness.day != today:
                            raise ValueError("Recovery record must be for the requested day")
                    except Exception:
                        # Optional recovery endpoints cannot fail an otherwise successful sync.
                        readiness = DailyReadiness(day=today, fetched_at=datetime.now(UTC))
                    self.store.save_readiness(readiness)

                if client and hasattr(client, "heart_rate_zones"):
                    try:
                        zones = client.heart_rate_zones()
                    except GarminError:
                        zones = []
                    self.store.save_garmin_zones(zones)
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
        result = read_detail(self.store, activity_id)
        result.step_compliance = self.store.step_compliance().get(activity_id)
        return result

    def readiness(self) -> list[DailyReadiness]:
        return self.store.readiness_history()

    def daily_adjustment(
        self, request: DailyAdaptRequest | None = None, today: date | None = None
    ) -> DailyProposalView:
        request = request or DailyAdaptRequest()
        proposal = adapt_daily(self.store, today or date.today(), **request.model_dump())
        return DailyProposalView.model_validate(proposal.model_dump())

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
            # Fingerprint persisted training data, without presentation-only fields.
            return Proposal(adjustment=propose(self.store.plan(), self.store.activities(), number))


def read_activities(path: Path) -> list[Activity]:
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("Activities file must contain a JSON array")
    return [Activity.model_validate(a) for a in data]
