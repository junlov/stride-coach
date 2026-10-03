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

| Effort | HR reserve range | Multiplier on estimated easy pace |
| --- | --- | --- |
| Easy / long | 60 to 72% | 1.00 |
| Recovery | 50 to 65% | 1.08 |
| Tempo | 78 to 87% | 0.83 |
| Intervals | 85 to 93% | 0.75 |
| Walk | 35 to 55% | HR only |

Pace bands extend from 96% to 106% of the multiplied seconds/km value.
Workout targets are pace or HR, not both. Whole-session HR averages cannot capture the
intensity of each short interval, so adaptation does not score interval/run-walk averages
against step targets. Heat, hills, sensor errors, and fatigue can distort either measure.

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
warm-up and cool-down; intervals alternate four controlled efforts with recovery.

Return-to-running sessions use six run/walk pairs. The initial running fraction is 33%,
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
Scale the target and all later weeks by that factor. Retain all triggered reasons.
Applying a week twice returns its stored result, preventing repeated compounding.
A "harder" observation describes the recorded target deviation; it does not diagnose fatigue.
