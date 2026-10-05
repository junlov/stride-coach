"""Optional Garmin recovery parsing and deterministic, confirmation-only softening."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

from .engine import make_steps
from .models import Kind
from .recovery_models import DailyProposal, DailyReadiness


def mapping(value):
    return value if isinstance(value, dict) else {}


def score(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if 0 <= value <= 100 and value == int(value) else None


def on_day(value, day):
    value = mapping(value)
    return value if value.get("calendarDate", day.isoformat()) == day.isoformat() else {}


def parse_readiness(day: date, training=None, hrv=None, sleep=None) -> DailyReadiness:
    if isinstance(training, list):
        candidates = [row for item in training if (row := on_day(item, day))]
        training = next(
            (r for r in candidates if r.get("inputContext") == "AFTER_WAKEUP_RESET"),
            next(iter(candidates), {}),
        )
    training = on_day(training, day)
    hrv = on_day(mapping(hrv).get("hrvSummary"), day)
    sleep = on_day(mapping(sleep).get("dailySleepDTO"), day)
    status = hrv.get("status")
    status = status.upper() if isinstance(status, str) else None
    if status not in {"BALANCED", "UNBALANCED", "LOW", "POOR", "UNKNOWN"}:
        status = None
    return DailyReadiness(
        day=day,
        fetched_at=datetime.now(UTC),
        training_readiness=score(training.get("score")),
        hrv_status=status,
        sleep_score=score(mapping(mapping(sleep.get("sleepScores")).get("overall")).get("value")),
    )


def poor_recovery(readiness: DailyReadiness) -> list[str]:
    reasons = []
    if readiness.training_readiness is not None and readiness.training_readiness < 25:
        reasons.append(f"Training Readiness is {readiness.training_readiness}/100 (below 25).")
    if readiness.sleep_score is not None and readiness.sleep_score < 50:
        reasons.append(f"Sleep score is {readiness.sleep_score}/100 (below 50).")
    if readiness.hrv_status in {"LOW", "POOR"}:
        reasons.append(f"HRV status is {readiness.hrv_status.lower()}.")
    return reasons


def propose_daily(store, today: date) -> DailyProposal:
    plan = store.plan()
    readiness = store.readiness(today)
    result = DailyProposal(day=today, readiness=readiness, reasons=[])
    if readiness is None:
        result.reasons = ["No recovery data for today. Sync Garmin before reviewing tomorrow."]
        return result
    result.reasons = poor_recovery(readiness)
    if not result.reasons:
        result.reasons = [
            "No poor-recovery rule triggered. Missing readings are not treated as poor recovery."
        ]
        return result
    workouts = [
        w
        for w in plan.workouts
        if w.day == today + timedelta(days=1) and w.kind in (Kind.TEMPO, Kind.INTERVALS)
    ]
    if not workouts:
        result.reasons.append("No hard workout tomorrow to soften.")
        return result
    workout = workouts[0]
    if store.daily_adjustment(workout.id):
        result.reasons.append("This workout already has a confirmed daily change.")
        return result
    result.before = workout
    result.after = workout.model_copy(
        update={
            "kind": Kind.EASY,
            "steps": make_steps(Kind.EASY, workout.minutes, plan.fitness, plan.setup, workout.week),
        }
    )
    result.after = store.resolve_workout_targets(result.after)
    result.garmin_update_required = store.scheduled(workout.id) is not None
    result.reasons.append("Replace tomorrow's hard workout with easy running at the same duration.")
    evidence = {
        "rule_version": "recovery-v1",
        "plan": plan.model_dump(mode="json"),
        "proposal": result.model_dump(mode="json"),
    }
    result.proposal_fingerprint = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result


def adapt_daily(store, today: date, *, apply=False, proposal_fingerprint=None) -> DailyProposal:
    with store.lock():
        if apply and proposal_fingerprint:
            previous = store.daily_adjustment_by_fingerprint(proposal_fingerprint)
            if previous:
                return previous
        proposal = propose_daily(store, today)
        if apply:
            if (
                not proposal.after
                or not proposal_fingerprint
                or proposal_fingerprint != proposal.proposal_fingerprint
            ):
                raise ValueError(
                    "The daily preview is missing or stale. "
                    "Preview tomorrow's change again before confirming."
                )
            store.apply_daily(proposal)
            proposal.applied = True
        return proposal
