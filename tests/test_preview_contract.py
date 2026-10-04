from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import Mock

import pytest

from stride_coach.adaptation import adapt, propose
from stride_coach.models import Activity


@pytest.fixture(autouse=True)
def database():
    return None


@pytest.mark.parametrize("change", ["activities", "plan", "missing"])
def test_apply_rejects_unreviewed_inputs(plan, change):
    monday = plan.setup.start + timedelta(weeks=1)
    preview = propose(plan, [], 2)
    fingerprint = preview.inputs["proposal_fingerprint"]
    store = Mock()
    store.lock.side_effect = nullcontext
    store.adjustment.return_value = None
    store.plan.return_value = plan
    store.activities.return_value = []
    store.sync_window.return_value = {
        "since": str(monday - timedelta(days=14)),
        "until": str(monday - timedelta(days=1)),
    }
    if change == "activities":
        store.activities.return_value = [
            Activity(
                id="late-sunday-run", day=monday - timedelta(days=1), duration_min=30, distance_km=5
            )
        ]
    elif change == "plan":
        plan.workouts[-1].steps[0].minutes += 1
    else:
        fingerprint = None
    before = plan.model_copy(deep=True)
    with pytest.raises(ValueError, match="review the new proposal"):
        adapt(store, 2, monday, apply=True, proposal_fingerprint=fingerprint)
    store.apply.assert_not_called()
    assert plan == before
    fresh = propose(plan, store.activities(), 2)
    result = adapt(
        store,
        2,
        monday,
        apply=True,
        proposal_fingerprint=fresh.inputs["proposal_fingerprint"],
    )
    store.apply.assert_called_once_with(plan, result)
    assert result.factor == fresh.factor
