# Workout text on Garmin and in the app

Names lead with the session type and its duration or main set. Easy and long runs use total
time. Tempo and interval sessions use the working efforts, excluding warmup, cooldown and
recoveries. Run-walk sessions use total time, including walking. The plan engine, durations,
targets and executable step structure are unchanged.

`src/stride_coach/workout_text.py` is the shared formatter. API workout summaries expose
`name` to the app; Garmin push previews and uploads use the same value. Names are computed
from the current steps, so an adapted workout gets an updated duration.

## Name length

[Garmin's support guidance](https://support.garmin.com/sl-SI/?faq=IPTtCv5SVs0bRf6l7nryz8)
says many devices only consider the first 15 characters of a workout name. The installed
`garminconnect` library's `BaseWorkout.workoutName` is an unconstrained string, and
`upload_workout` passes the supplied payload through. Stride Coach therefore caps names
at 15 ASCII characters for watch compatibility, rather than relying on client validation.

Examples: `Easy Run 40 min`, `Long Run 75 min`, `Tempo 3 x 8 min`, `Run-Walk 30 min`,
`Recovery 25 min`, `Intervals 4x3m`. Longer names first drop "Jog" from recovery, then compact
units and repetition spacing, then shorten "Intervals" to "Reps" before a final safe slice.
Seconds are shown for short efforts, and fractional minutes use minutes:seconds.
The complete duration and targets remain in the steps. No plan position is added.

Identical type/duration names can recur across the plan. Garmin warns that devices can
collapse names with the same first 15 characters; this naming change does not guarantee
distinct on-device storage for identical sessions. Remote ownership and scheduling use
tags and IDs, never human names.

## Payload example

This synthetic easy run illustrates the actual upload shape:

```json
{
  "workoutName": "Easy Run 40 min",
  "description": "Build endurance at an easy effort where you can chat comfortably. Aim for 130 to 145 bpm during the running efforts.\nstride-coach:v1:synthetic",
  "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
  "estimatedDurationInSecs": 2400,
  "workoutSegments": [{
    "segmentOrder": 1,
    "sportType": {"sportTypeId": 1, "sportTypeKey": "running"},
    "workoutSteps": [{
      "type": "ExecutableStepDTO",
      "stepOrder": 1,
      "description": "40 min easy run at 130 to 145 bpm",
      "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
      "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
      "endConditionValue": 2400,
      "targetType": {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone"},
      "targetValueOne": 130,
      "targetValueTwo": 145
    }]
  }]
}
```

Pace steps show text such as `8 min at 5:05 to 5:15 /km`; Garmin numeric pace targets remain
in meters per second. Warmup, cooldown, walks and recovery jogs get plain instructions.
Guidance uses the existing main-step targets. Mixed targets direct the runner to each step.

## Ownership and migration

The exact `stride-coach:v1:<id>` tag is its own final description line. Discovery accepts both
old exact-tag descriptions and new descriptions containing that exact line. Old `SC <id>`
names only narrow discovery; the fetched workout must still contain the tag. Substrings,
extra suffixes and a matching name without a tag cannot authorize updates or deletion.
When inventory summaries omit descriptions, details are fetched to verify tags, even for
renamed workouts. This may require more read calls for inventories without descriptions.

A normal explicit push of an existing tagged workout uses the existing update endpoint
because its payload fingerprint changes. It keeps the remote ID and existing schedule.
The next identical push is skipped. Duplicate tags still stop writes for review.
Preview first, then use the existing explicit apply flow to update eligible workouts.

Tests use synthetic responses and block outbound Garmin calls. `examples/offline_demo.py`
executes the real CLI preview and checks that the view and payload names match, with no
Garmin credentials or writes. Live Garmin rendering has not been verified.
