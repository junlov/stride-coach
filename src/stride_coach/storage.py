"""Typed PostgreSQL storage with durable remote-write intent and atomic adaptation."""

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from .activity_models import RunCompliance, RunLap, StepCompliance
from .activity_storage import save_details
from .database import WRITE_LOCK, check_schema, connection_lock, database_url, make_engine, upgrade
from .db_models import (
    ActivityLapRow,
    ActivityRow,
    AdjustmentRow,
    DailyAdjustmentRow,
    GarminZoneRow,
    MatchRow,
    MetadataRow,
    PlanRow,
    ReadinessRow,
    RepeatRow,
    ScheduledRow,
    StepComplianceRow,
    StepKind,
    StepRow,
    SyncAttemptRow,
    WeekRow,
    WorkoutRow,
    WriteIntentRow,
    WriteOperation,
)
from .models import (
    Activity,
    ActivityCore,
    Adjustment,
    Athlete,
    Fitness,
    GarminHeartRateZone,
    Plan,
    RepeatGroup,
    Setup,
    Step,
    Workout,
    executable_steps,
)
from .recovery_models import DailyProposal, DailyReadiness
from .sync_models import SyncAttempt, SyncStatus


def fields(row, model):
    return {name: getattr(row, name) for name in model.model_fields}


def step_kind(label: str) -> StepKind:
    label = label.lower()
    if label == "warm up":
        return StepKind.WARMUP
    if label == "cool down":
        return StepKind.COOLDOWN
    if "walk" in label or "recovery" in label:
        return StepKind.RECOVERY
    return StepKind.INTERVAL


class Store:
    def __init__(self, url: str | None = None, read_only: bool = False, migrate: bool = True):
        self.url = database_url(url)
        if migrate and not read_only:
            upgrade(self.url)
        self.engine = make_engine(self.url)
        self.connection = self.engine.connect()
        try:
            if read_only:
                self.connection.execute(
                    text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
                )
                self.connection.commit()
            check_schema(self.connection)
            self.connection.commit()
        except Exception:
            self.close()
            raise

    def close(self):
        self.connection.close()
        self.engine.dispose()

    @contextmanager
    def transaction(self):
        with Session(self.connection) as session, session.begin():
            yield session

    @contextmanager
    def lock(self):
        with connection_lock(self.connection, WRITE_LOCK):
            yield

    @contextmanager
    def try_lock(self):
        acquired = self.connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": WRITE_LOCK}
        )
        self.connection.commit()
        try:
            yield acquired
        finally:
            if acquired:
                self.connection.rollback()
                self.connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": WRITE_LOCK}
                )
                self.connection.commit()

    def save_attempt(self, attempt: SyncAttempt):
        with self.transaction() as session:
            session.merge(SyncAttemptRow(**attempt.model_dump()))

    def sync_status(self) -> SyncStatus:
        with self.transaction() as session:

            def latest(*conditions):
                row = session.scalar(
                    select(SyncAttemptRow)
                    .where(*conditions)
                    .order_by(SyncAttemptRow.started_at.desc())
                    .limit(1)
                )
                return SyncAttempt(**fields(row, SyncAttempt)) if row else None

            return SyncStatus(
                latest=latest(),
                last_success=latest(SyncAttemptRow.result == "success"),
                history=latest(SyncAttemptRow.source == "history"),
            )

    def latest_regular_sync(self):
        with self.transaction() as session:
            row = session.scalar(
                select(SyncAttemptRow)
                .where(SyncAttemptRow.source != "history")
                .order_by(SyncAttemptRow.started_at.desc())
                .limit(1)
            )
            return SyncAttempt(**fields(row, SyncAttempt)) if row else None

    def save_history_page(self, attempt: SyncAttempt, activities: list[Activity]):
        # Cursor and upserts commit together. A crash can only replay the uncommitted page.
        with self.transaction() as session:
            for activity in activities:
                session.merge(
                    ActivityRow(**activity.model_dump(include=set(ActivityCore.model_fields)))
                )
                session.flush()
                save_details(session, activity)
            session.merge(SyncAttemptRow(**attempt.model_dump()))
            self._refresh_matches(session)

    def _plan(self, session) -> Plan:
        row = session.scalar(select(PlanRow))
        if row is None:
            raise ValueError("No plan. Run stride-coach init first.")
        steps = {}
        groups = {
            (group.workout_id, group.position): group
            for group in session.scalars(select(RepeatRow))
        }
        zones = {
            zone.zone: zone
            for zone in session.scalars(
                select(GarminZoneRow).where(
                    GarminZoneRow.fetched_at >= datetime.now(UTC) - timedelta(days=7)
                )
            )
        }
        children = {}
        for leaf in session.scalars(select(StepRow).order_by(StepRow.position)):
            step = Step(**fields(leaf, Step))
            zone = zones.get(step.preferred_hr_zone)
            if zone is not None:
                step.hr_zone = zone.zone
                step.hr_min, step.hr_max = zone.lower_bpm, zone.upper_bpm
            target = steps.setdefault(leaf.workout_id, [])
            if leaf.group_position is None:
                target.append(step)
            else:
                key = (leaf.workout_id, leaf.group_position)
                if key not in children:
                    children[key] = []
                    target.append(key)
                children[key].append(step)
        for target in steps.values():
            for index, entry in enumerate(target):
                if isinstance(entry, tuple):
                    group = groups[entry]
                    target[index] = RepeatGroup(
                        label=group.label,
                        repetitions=group.repetitions,
                        skip_last_rest=group.skip_last_rest,
                        steps=children[entry],
                    )
        workouts = [
            Workout(
                **{key: getattr(w, key) for key in Workout.model_fields if key != "steps"},
                steps=steps.get(w.id, []),
            )
            for w in session.scalars(select(WorkoutRow).order_by(WorkoutRow.position))
        ]
        return Plan(
            id=row.id,
            setup=Setup(
                goal=row.goal,
                start=row.start,
                race_date=row.race_date,
                days_per_week=row.days_per_week,
                long_run_day=row.long_run_day,
                athlete=Athlete(**fields(row, Athlete)),
            ),
            fitness=Fitness(
                vdot=row.vdot,
                easy_pace=row.easy_pace,
                weekly_minutes=row.weekly_minutes,
                source=row.fitness_source,
            ),
            workouts=workouts,
            warnings=row.warnings,
        )

    def save_garmin_zones(self, zones: list[GarminHeartRateZone]):
        with self.lock(), self.transaction() as session:
            session.execute(delete(GarminZoneRow))
            session.add_all(
                GarminZoneRow(**zone.model_dump(), fetched_at=datetime.now(UTC)) for zone in zones
            )

    def plan(self) -> Plan:
        with self.transaction() as session:
            return self._plan(session)

    def _initialize(self, session, plan):
        if session.scalar(select(PlanRow.id)) is not None:
            raise ValueError("A plan already exists. Use a different database for a new plan.")
        session.add(
            PlanRow(
                id=plan.id,
                **plan.setup.model_dump(exclude={"athlete"}),
                **plan.setup.athlete.model_dump(),
                **plan.fitness.model_dump(exclude={"source"}),
                fitness_source=plan.fitness.source,
                warnings=plan.warnings,
            )
        )
        session.flush()
        session.add_all(WeekRow(plan_id=plan.id, number=n) for n in {w.week for w in plan.workouts})
        session.flush()
        session.add_all(
            WorkoutRow(**w.model_dump(exclude={"steps"}), plan_id=plan.id, position=position)
            for position, w in enumerate(plan.workouts)
        )
        session.flush()
        for workout in plan.workouts:
            position = 0
            for block in workout.steps:
                group_position = position if isinstance(block, RepeatGroup) else None
                if group_position is not None:
                    session.add(
                        RepeatRow(
                            workout_id=workout.id,
                            position=position,
                            **block.model_dump(exclude={"steps"}),
                        )
                    )
                for step in executable_steps([block]):
                    session.add(
                        StepRow(
                            **step.model_dump(),
                            workout_id=workout.id,
                            position=position,
                            group_position=group_position,
                            kind=step_kind(step.label),
                        )
                    )
                    position += 1
        session.flush()

    def _refresh_matches(self, session):
        from .adaptation import match_activities
        from .compliance import score_steps

        session.flush()
        session.execute(delete(MatchRow))
        if session.scalar(select(PlanRow.id)) is not None:
            plan = self._plan(session)
            workouts = {w.id: w for w in plan.workouts}
            laps = {}
            for row in session.scalars(select(ActivityLapRow).order_by(ActivityLapRow.position)):
                laps.setdefault(row.activity_id, []).append(RunLap(**fields(row, RunLap)))
            matches = match_activities(plan, self._activities(session))
            session.add_all(MatchRow(**match) for match in matches)
            session.flush()
            for match in matches:
                result = score_steps(
                    workouts[match["workout_id"]], laps.get(match["activity_id"], [])
                )
                session.add_all(
                    StepComplianceRow(workout_id=result.workout_id, **step.model_dump())
                    for step in result.steps
                )

    def step_compliance(self) -> dict[str, RunCompliance]:
        with self.transaction() as session:
            scores = {}
            for row in session.scalars(
                select(StepComplianceRow).order_by(StepComplianceRow.position)
            ):
                scores.setdefault(row.workout_id, []).append(
                    StepCompliance(**fields(row, StepCompliance))
                )
            result = {}
            for row in session.scalars(select(MatchRow)):
                steps = scores.get(row.workout_id, [])
                if steps:
                    known = [step.score for step in steps if step.score is not None]
                    result[row.activity_id] = RunCompliance(
                        workout_id=row.workout_id,
                        score=sum(known) / len(known) if known else None,
                        scored_steps=len(known),
                        missing_steps=len(steps) - len(known),
                        steps=steps,
                    )
            return result

    def save_readiness(self, readiness: DailyReadiness):
        with self.transaction() as session:
            # Replace the entire snapshot so unavailable values cannot look freshly fetched.
            session.merge(ReadinessRow(**readiness.model_dump()))

    def readiness(self, day: date) -> DailyReadiness | None:
        with self.transaction() as session:
            row = session.get(ReadinessRow, day)
            return DailyReadiness(**fields(row, DailyReadiness)) if row else None

    def readiness_history(self, limit=30) -> list[DailyReadiness]:
        with self.transaction() as session:
            return [
                DailyReadiness(**fields(row, DailyReadiness))
                for row in session.scalars(
                    select(ReadinessRow).order_by(ReadinessRow.day.desc()).limit(limit)
                )
            ]

    @staticmethod
    def _daily_proposal(row):
        return (
            DailyProposal(
                **{
                    key: getattr(row, key) for key in DailyProposal.model_fields if key != "applied"
                },
                applied=True,
            )
            if row
            else None
        )

    def daily_adjustment(self, workout_id):
        with self.transaction() as session:
            return self._daily_proposal(session.get(DailyAdjustmentRow, workout_id))

    def daily_adjustment_by_fingerprint(self, fingerprint):
        with self.transaction() as session:
            return self._daily_proposal(
                session.scalar(
                    select(DailyAdjustmentRow).where(
                        DailyAdjustmentRow.proposal_fingerprint == fingerprint
                    )
                )
            )

    def daily_adjustments(self):
        with self.transaction() as session:
            return [
                self._daily_proposal(row)
                for row in session.scalars(
                    select(DailyAdjustmentRow).order_by(DailyAdjustmentRow.day)
                )
            ]

    def apply_daily(self, proposal: DailyProposal):
        workout = proposal.after
        with self.transaction() as session:
            if session.get(DailyAdjustmentRow, workout.id):
                raise ValueError("This workout already has a confirmed daily change.")
            session.get(WorkoutRow, workout.id).kind = workout.kind
            session.execute(delete(StepRow).where(StepRow.workout_id == workout.id))
            session.add_all(
                StepRow(
                    workout_id=workout.id,
                    position=i,
                    kind=step_kind(step.label),
                    **step.model_dump(),
                )
                for i, step in enumerate(workout.steps)
            )
            session.add(
                DailyAdjustmentRow(
                    workout_id=workout.id,
                    **proposal.model_dump(mode="json", exclude={"applied", "day"}),
                    day=proposal.day,
                )
            )
            self._refresh_matches(session)

    def initialize(self, plan: Plan):
        with self.lock(), self.transaction() as session:
            self._initialize(session, plan)
            self._refresh_matches(session)

    def _activities(self, session):
        return [
            Activity(**fields(row, ActivityCore))
            for row in session.scalars(select(ActivityRow).order_by(ActivityRow.id))
        ]

    def activities(self) -> list[Activity]:
        with self.transaction() as session:
            return self._activities(session)

    def save_sync(
        self, activities: list[Activity], since: str, until: str, *, today: date | None = None
    ):
        begin, end = date.fromisoformat(since), date.fromisoformat(until)
        today = today or date.today()
        if begin > end or end > today:
            raise ValueError("Sync needs since <= until <= today")
        complete_end = min(end, today - timedelta(days=1))
        with self.lock(), self.transaction() as session:
            # Preserve children for activities still present in the authoritative window.
            ids = [a.id for a in activities if begin <= a.day <= end]
            session.execute(
                delete(ActivityRow).where(
                    ActivityRow.day.between(begin, end), ActivityRow.id.not_in(ids)
                )
            )
            for activity in activities:
                if begin <= activity.day <= end:
                    session.merge(
                        ActivityRow(**activity.model_dump(include=set(ActivityCore.model_fields)))
                    )
                    session.flush()
                    save_details(session, activity)
            session.merge(
                MetadataRow(key="sync", since=begin, until=end, updated_at=datetime.now(UTC))
            )
            session.merge(
                MetadataRow(
                    key="sync_complete",
                    since=begin if begin <= complete_end else None,
                    until=complete_end if begin <= complete_end else None,
                    updated_at=datetime.now(UTC),
                )
            )
            self._refresh_matches(session)

    def sync_window(self, *, complete: bool = False) -> dict:
        with self.transaction() as session:
            row = session.get(MetadataRow, "sync_complete" if complete else "sync")
            return {"since": str(row.since), "until": str(row.until)} if row and row.since else {}

    def scheduled(self, workout_id: str):
        with self.transaction() as session:
            row = session.get(ScheduledRow, workout_id)
            return (
                {
                    key: getattr(row, key)
                    for key in ("workout_id", "remote_id", "fingerprint", "scheduled")
                }
                if row
                else None
            )

    def scheduled_count(self) -> int:
        with self.transaction() as session:
            return session.scalar(select(func.count()).select_from(ScheduledRow))

    def save_remote(self, workout_id: str, remote_id: str, fingerprint: str, scheduled: bool):
        with self.transaction() as session:
            session.merge(
                ScheduledRow(
                    workout_id=workout_id,
                    remote_id=remote_id,
                    fingerprint=fingerprint,
                    scheduled=scheduled,
                )
            )

    def forget_remote(self, workout_id: str):
        with self.transaction() as session:
            session.execute(delete(ScheduledRow).where(ScheduledRow.workout_id == workout_id))

    def pending(self, key: str, state: bool | None = None) -> bool:
        operation, workout_id = key.split(":", 1)
        identity = (workout_id, WriteOperation(operation))
        with self.transaction() as session:
            row = session.get(WriteIntentRow, identity)
            if state is True and row is None:
                session.add(WriteIntentRow(workout_id=workout_id, operation=identity[1]))
            elif state is False and row is not None:
                session.delete(row)
            return state if state is not None else row is not None

    def adjustment(self, week: int) -> Adjustment | None:
        with self.transaction() as session:
            row = session.scalar(select(AdjustmentRow).where(AdjustmentRow.week == week))
            return Adjustment(**fields(row, Adjustment)) if row else None

    def adjustments(self) -> list[Adjustment]:
        with self.transaction() as session:
            return [
                Adjustment(**fields(row, Adjustment))
                for row in session.scalars(select(AdjustmentRow).order_by(AdjustmentRow.week))
            ]

    def apply(self, plan: Plan, adjustment: Adjustment):
        with self.lock(), self.transaction() as session:
            if session.get(AdjustmentRow, (plan.id, adjustment.week)):
                raise ValueError("This week was already adapted; repeated reductions are blocked.")
            steps = {
                (row.workout_id, row.position): row
                for row in session.scalars(
                    select(StepRow).join(WorkoutRow).where(WorkoutRow.plan_id == plan.id)
                )
            }
            # Scale time and distance while keeping workout identity and every remote ledger row.
            for workout in plan.workouts:
                for position, step in enumerate(executable_steps(workout.steps)):
                    row = steps[workout.id, position]
                    row.minutes = step.minutes
                    row.distance_m = step.distance_m
            session.add(
                AdjustmentRow(
                    plan_id=plan.id, **adjustment.model_dump(exclude={"applied"}), applied=True
                )
            )
            self._refresh_matches(session)
        adjustment.applied = True
