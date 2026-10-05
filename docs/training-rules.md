# Training rules and provenance

The executable rules live in [`engine.py`](../src/stride_coach/engine.py) and
[`adaptation.py`](../src/stride_coach/adaptation.py). Thresholds below are this project's
conservative engineering choices, not validated individual coaching prescriptions.
No commercial sessions or plan templates were copied.

## Fitness and baseline

Use running activities in the 28 days before plan start. Weekly minutes are the total divided
by four, including empty weeks. The initial plan uses this average, capped at 360 minutes.
With no running history, start at 20 minutes per selected day. Return to running starts at
at most 60 total minutes. Very sparse history can yield very short sessions; inspect the plan.

For a marked best effort of at least 3 km and 12 minutes, calculate a Daniels/Gilbert-style
performance score. With velocity `v` in metres/minute and duration `t` in minutes:

```text
oxygen_cost = -4.60 + 0.182258*v + 0.000104*v*v
fraction = 0.8 + 0.1894393*exp(-0.012778*t) + 0.2989558*exp(-0.1932605*t)
score = oxygen_cost / fraction
```

Take the best plausible score (15 to 85) and reduce it 3%. Solve the oxygen-cost curve at
65% of that score for an approximate easy pace. This is a VDOT-style approximation, not an
implementation of licensed pace tables or a measured VO2 max. [VDOT's own explanation](
https://news.vdoto2.com/2017/11/what-is-vdot/) describes using recent performance to guide paces.

Without a marked effort, at least three recent runs of 2 km or more provide the median pace,
slowed by 10% with a floor of 7 minutes/km. Thinner data uses heart-rate reserve targets.
HR reserve is `max_hr - resting_hr`; target HR is `resting_hr + fraction * reserve`.

| Effort | HR reserve fallback | Garmin zone when known | Pace multiplier |
| --- | --- | --- | --- |
| Easy / long | 60 to 72% | 2 | HR target |
| Recovery | 50 to 65% | 1 | HR target |
| Tempo | 78 to 87% | HR fallback only | 0.83 |
| Intervals / strides | 85 to 93% | HR fallback only | 0.75 |
| Walk | 35 to 55% | HR range | HR target |

Easy, long, warm-up, cool-down and recovery steps use the numbered zone from current
Garmin running settings when available. Ordinary Garmin sync reads
`/biometric-service/heartRateZones/`, preferring RUNNING over DEFAULT. It stores validated
bounds separately from historical activity zones. The cached settings expire after seven
days; a failed zone read clears them. Missing, invalid or expired settings use the HR-reserve
range above. A plan preview and its Garmin preview use the same cached zones; push never
fetches different targets after confirmation. Garmin resolves a numbered zone using the
watch settings, so sync the watch after changing its zones. Historical activity zones are
not evidence of the watch's current configuration.

Tempo and intervals retain pace ranges when pace can be estimated. Their bands normally
extend from 96% to 106% of the multiplied seconds/km value. The minimum total spread is
20 seconds/km, centered on 101% of that value and rounded outward to whole seconds.
This avoids very narrow bands that alert on ordinary pace variation. Thin history retains
HR-reserve fallbacks.

Strides can also carry a secondary cadence band, centered on the median cadence, plus or minus 10 steps/min.
This requires at least three runs from the 28 days before plan start.
Only measured cadences from 100 to 230 steps/min qualify. Plan creation uses supplied runs
or stored cadence measurements, without loading activity streams. Absent history means no cadence target.

Whole-session HR averages cannot capture the intensity of each short interval, so adaptation
does not score interval/run-walk averages against step targets. Heat, hills, sensor errors,
and fatigue can distort either measure. Zone bounds support local comparisons; the uploaded
zone target uses `zoneNumber`, without an absolute BPM target alongside it.

## Periodization

Base occupies roughly the first 30% (at least two weeks), followed by build, two peak weeks,
and a two-week taper (three for marathon). Every fourth non-taper week cuts time 15%.
Other weeks increase at most 8% from the immediately previous week, including after cutbacks.
Taper weeks reduce time 25%. There is no sudden restoration to the pre-cutback volume.
The final week may be partial because training stops before the race/completion date.

Time caps are 240 minutes for 5k, 300 for 10k, 360 for half, 480 for marathon, and 120 for
return to running. These are ceilings, not mandatory targets. Short horizons and sparse
history can leave a runner far below race demands. The tool warns about low half/marathon
baselines and never accelerates progression to force race readiness.

The selected days are spaced around the long run. With two days, time is split evenly.
With more days, the long run gets `1 / days + 0.10` of weekly time. At most one tempo or
interval workout appears in a build/peak week, only with at least three training days and
90 recent weekly minutes. Cutbacks omit quality work. Tempo and interval sessions include
warm-up and cool-down that end with the Lap button, with estimated minutes retained for
planning. Intervals use one repeat group of four controlled efforts and recoveries, skipping
the final recovery. With an estimated pace, effort and recovery distances round down to
100 m increments within their original time budgets. Otherwise they remain timed. The
remaining session time is split equally between warm-up and cool-down. A distance step's
minutes are an estimate, not a second watch end condition. Explicit structured steps can
also represent sessions such as 6 x 800 m with 400 m jog recoveries.

Easy runs of at least 20 minutes with an estimated pace finish with four 20-second relaxed
strides, each followed by 40 seconds of easy recovery. Those four minutes come out of the
easy portion, preserving total planned time. Short sessions and thin-history sessions omit
strides. Return-to-running uses its dedicated run/walk structure instead.

Return-to-running sessions use one repeat group of six run/walk pairs, including the final walk. The initial running fraction is 33%,
increasing by a factor of 1.01 each week, capped at 70%. Combined with at most 8% session-time
growth, running time also grows less than 10% week to week. The program intentionally does
not promise continuous running at its end. Its selected days have recovery days between them.

Periodized base/build/taper structure is widely published; the [Boston Athletic Association's
training overview](https://www.baa.org/races/boston-marathon/info-for-athletes/boston-marathon-training/)
is one example. We use the general principles, not its daily sessions. The 10% ceiling is a
planning constraint, not a scientifically guaranteed injury boundary.

## Load and adjustment

Banister TRIMP uses session-average HR, duration in minutes, and HR reserve:

```text
r = clamp((average_hr - resting_hr) / (max_hr - resting_hr), 0, 1)
TRIMP = duration * r * a * exp(b * r)
```

Default coefficients are `a=0.64`, `b=1.92`; `init --trimp-a` and `--trimp-b` configure them.
The alternate published pair `0.86`, `1.67` can be selected explicitly. The tool does not
infer a coefficient set from identity. Published discussions of the average-HR formula and
its limitations include [this training-load study](https://pmc.ncbi.nlm.nih.gov/articles/PMC4685065/)
and [the swimmers' comparison](https://pubmed.ncbi.nlm.nih.gov/24942164/). This is not a
zone-points sum; higher resting HR reduces relative reserve at the same average HR.

Only running activities count in v1. Load includes unmatched extra runs too. Missing HR
contributes no numeric load but increments an explicit missing count, and disables the
load-rise comparison. Do not interpret a displayed zero with missing HR as zero exertion.

| Observation in the completed week | Action on the planned coming week |
| --- | --- |
| Fewer than 50% sessions matched | Reduce 25% |
| 50% to less than 80% matched | Reduce 10% |
| A missed session with at least 80% matched | Hold at no more than last week's planned time |
| Missing HR in either compared week | Hold at no more than last week's planned time |
| TRIMP rises over 20% from a nonzero prior week | Reduce 15% |
| Easy/long/recovery HR over target high + 8 bpm, or pace over 10% faster | Reduce 10% |
| HR below target low - 8 bpm, or pace over 15% slower | Hold and review targets |
| Completed running duration below 70% of planned | Reduce 15% |
| None of these | Retain the existing planned progression |

Apply the smallest factor, never stack reductions or increase beyond the generated plan.
Scale the target and all later weeks by that factor. Scale both estimated minutes and
any distance end condition, including repeat children, without changing repeat counts.
Repeat totals multiply child time by the count and exclude a skipped final recovery.
Lap-ended steps can last longer or shorter in practice; training load uses recorded activity
time after the run. Retain all triggered reasons.
Repeating an apply with its accepted proposal fingerprint returns the stored result without compounding reductions.
See the [weekly loop](../README.md#weekly-loop) for the confirmation contract.
A "harder" observation describes the recorded target deviation; it does not diagnose fatigue.

## Step compliance from captured laps

[`compliance.py`](../src/stride_coach/compliance.py) implements `laps-v1`.
The scorer expands repeat groups and omits a skipped final recovery before it aligns laps.
Match runs with the existing date/type rule first. Inferred matches remain labeled.

Multi-step scoring requires equal lap and expanded step counts.
Each lap duration must fall within 90% to 110% of its planned step estimate,
including distance and Lap-ended steps. Otherwise, the scorer marks step alignment
as unverified and reports no step failures. Equal counts alone do not establish step boundaries.

For one continuous step, combine all recorded laps. Absent laps and absent target measurements
produce unavailable scores. Automatic kilometer laps cannot reliably identify interval boundaries.

Each step has two checks, with equal weight:

- Duration: 100 points within 90% to 110% of planned seconds, inclusive; otherwise zero.
- Target: the percentage of recorded lap seconds whose average pace or HR is inside the
  planned band, inclusive. Use pace when both pace limits exist, otherwise HR when both HR
  limits exist. Derive pace from lap duration and distance when its average is absent.

The step score is the mean of those checks. Missing target data leaves the combined score
unavailable while preserving the duration check. The run score is the mean of its fully scored
steps, accompanied by scored and unavailable counts. A partially scored run is not 100% proven
compliant even if its available steps score 100. Zero HR and zero-distance laps without pace
are unavailable target data. Lap averages cannot establish second-by-second time in zone.

Reads recalculate scores from saved laps and the plan's current resolved targets.
Zone changes, removal, and expiry therefore affect scores, including the HR-reserve fallback.
Read-only Store and MCP access neither writes scores nor contacts Garmin.
Sync, detail backfill, history import, plan creation, confirmed adaptation, and zone replacement
also refresh stored score snapshots.
These scores provide runner feedback. Weekly volume rules and run classification do not use them.

## Daily recovery proposal

[`recovery.py`](../src/stride_coach/recovery.py) implements `recovery-v1`. Each ordinary Garmin
sync reads **the current server-local day** once for Training Readiness, HRV status, and sleep
score, independent of the requested activity date range. History import does not backfill
recovery data. Each day stores its fetch timestamp and nullable, typed observations. A later
sync replaces that day's entire snapshot, including unavailable values. Unsupported devices,
missing fields, and provider errors never make the activity sync fail. No prior day's reading
is substituted for today. Morning Training Readiness is preferred when Garmin identifies it;
otherwise the first same-day reading is used. Mismatched provider dates are discarded.

Any of these observations triggers poor recovery:

| Today's observation | Threshold |
| --- | --- |
| Training Readiness | Less than 25 out of 100 |
| Sleep score | Less than 50 out of 100 |
| HRV status | `LOW` or `POOR` |

Boundaries 25 and 50 do not trigger. `UNBALANCED`, `UNKNOWN`, unrecognized HRV statuses, and
missing scores do not independently trigger. Retain all triggered reasons. These are
conservative project rules, not individually validated medical or coaching prescriptions.

Only tomorrow's tempo or interval workout can change. The preview replaces its steps with
an easy workout at the same total estimated duration. The replacement follows the
[session structure rules](#periodization), including eligible strides.
The server resolves replacement targets through the same zone rules as plan reads
before it creates descriptions and the proposal fingerprint.
It preserves the workout ID, date, week, and remote mapping. It never adds a workout,
increases minutes, moves a rest day, or restores previously reduced volume.

The daily preview is available on every day of the week. It is separate from the **Monday
weekly adjustment window**, which still requires two complete weeks of sync coverage and
retains its existing volume caps and propagation rules. Daily softening does not need that
history because it only reduces tomorrow's intensity. A Monday weekly adjustment can still
reduce the duration of a softened workout and later weeks. It never restores its hard type.

Preview reads do not save a plan change. Confirmation must include the fingerprint of the
reviewed preview; the server rechecks the day, complete plan, recovery snapshot, and Garmin
mapping under the existing write lock. A fresh sync or intervening plan change requires a new
preview. The plan edit and its reasons/before/after evidence commit together. Repeating an
accepted fingerprint returns its saved result without changing the plan again.

Confirmation only changes the local plan. No recovery read, proposal, or local confirmation writes to Garmin automatically.
For Garmin updates and removal scope, see the [calendar workflow](self-hosting.md#garmin-calendar-window).

## Garmin field evidence and supported fallbacks

The adapter follows the [python-garminconnect workout models](https://github.com/cyberjunky/python-garminconnect/blob/master/garminconnect/workout.py)
for repeat groups, numbered HR zones, secondary cadence targets and condition identifiers
(time 2, distance 3, Lap 1, iterations 7). The older pinned library has incorrect condition
constants, so the adapter supplies these confirmed identifiers explicitly. Every group and
child receives a unique step order. `skipLastRestStep` is evidenced by a
[recorded Garmin workout payload](https://gist.github.com/Zeko369/c4fa744e3d41a36c6cd0e22aac12e576).
The zone profile fields follow the [Garmin client zone model](https://pkg.go.dev/github.com/tamcore/garmin-mcp/internal/garmin/api#HeartRateZoneProfile).

No confirmed payload or client field was found for an HR-below recovery combined with a
time-cap fallback, or for repeat-until-Lap. Those combinations are intentionally not emitted:
recoveries keep their supported time/distance end condition and strides use four fixed
repetitions. Lap-button end conditions apply to executable warm-up and cool-down steps.
No live Garmin call or write is required to generate or test these payloads.
