import { ReactNode, useCallback, useState } from "react";
import { Client, Schema } from "../api/client";
import {
  Badge,
  Button,
  Card,
  Copy,
  Heading,
  Hero,
  Muted,
  Notice,
  QueryState,
} from "./ui";
import { WorkoutGraph } from "./workout-graph";
import { useQuery } from "../state/query";
export function pace(seconds: number) {
  const rounded = Math.round(seconds);
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, "0")}`;
}
type WorkoutStep = Schema<"Step"> | Schema<"RepeatGroup">;
export function stepMinutes(step: WorkoutStep): number {
  return "steps" in step
    ? step.repetitions * step.steps.reduce((sum, child) => sum + child.minutes, 0) -
        (step.skip_last_rest ? step.steps[step.steps.length - 1].minutes : 0)
    : step.minutes;
}
export function stepSummary(step: WorkoutStep): string {
  if ("steps" in step) {
    return `${step.label}: ${step.repetitions} x (${step.steps.map(stepSummary).join("; ")})${step.skip_last_rest ? " · Skip last recovery" : ""}`;
  }
  const end = step.end_condition === "lap"
    ? `press Lap (${step.minutes.toFixed(1)} min estimated)`
    : step.end_condition === "distance"
      ? `${Number(step.distance_m?.toFixed(1))} m`
      : `${step.minutes.toFixed(1)} min`;
  const target = step.hr_zone
    ? `Zone ${step.hr_zone}`
    : step.pace_min && step.pace_max
      ? `${pace(step.pace_min)} to ${pace(step.pace_max)} /km`
      : step.hr_min && step.hr_max ? `${step.hr_min} to ${step.hr_max} bpm` : "";
  const cadence = step.cadence_min && step.cadence_max
    ? ` · ${step.cadence_min} to ${step.cadence_max} spm` : "";
  return `${step.label}: ${end}${target ? ` · ${target}` : ""}${cadence}`;
}
export const workoutMinutes = (workout: Schema<"Workout">) =>
  workout.steps.reduce((sum, step) => sum + stepMinutes(step), 0);
export function WorkoutCard({
  workout,
  hero = false,
  match,
  children,
}: {
  workout: Schema<"Workout"> | Schema<"WorkoutSummary">;
  hero?: boolean;
  children?: ReactNode;
  match?: Schema<"Match">;
}) {
  const [why, setWhy] = useState(false);
  const [detail, setDetail] = useState(false);
  return (
    <Card>
      <Badge>
        {workout.cutback ? "Cutback" : workout.phase} · Week {workout.week}
      </Badge>
      <Heading>
        {workout.day} · {"name" in workout ? workout.name : workout.kind}
      </Heading>
      {hero ? (
        <Hero value={Math.round(workoutMinutes(workout))} unit="min" />
      ) : (
        <Copy>
          {Math.round(workoutMinutes(workout))} min · {workout.phase}
          {workout.cutback ? " · Cutback" : ""}
        </Copy>
      )}
      <WorkoutGraph workout={workout} />
      {workout.steps.map((step, i) => (
        <Muted key={i}>{stepSummary(step)}</Muted>
      ))}
      {children}
      <Button
        variant="secondary"
        label={why ? "Hide workout explanation" : "Why this workout?"}
        onPress={() => setWhy(!why)}
      />
      {why && (
        <Notice title="Your training context">
          <Copy>
            This is a {workout.kind} session in the {workout.phase} phase.
            {workout.cutback ? " This is a cutback workout." : ""}
          </Copy>
          <Muted>
            Follow the effort targets above. A personalized reason for this
            session is not available from your server.
          </Muted>
        </Notice>
      )}
      {match && (
        <>
          <Badge>Inferred match</Badge>
          <Button
            variant="secondary"
            label={detail ? "Close run detail" : "Review matched run"}
            onPress={() => setDetail(!detail)}
          />
          {detail && (
            <Notice title="Run detail">
              <Copy>Activity: {match.activity_id}</Copy>
              <Copy>Match method: {match.method}</Copy>
              <Muted>
                This association is inferred by your server, not confirmed by
                you.
              </Muted>
              <RunMeasurements
                key={match.activity_id}
                activityId={match.activity_id}
                plannedMinutes={workoutMinutes(workout)}
              />
            </Notice>
          )}
        </>
      )}
    </Card>
  );
}

function measurement(
  value: number | null | undefined,
  format: (value: number) => string,
) {
  return value == null ? "unavailable" : format(value);
}
function RunMeasurements({
  activityId,
  plannedMinutes,
}: {
  activityId: string;
  plannedMinutes: number;
}) {
  const query = useQuery(
    useCallback((client: Client) => client.activity(activityId), [activityId]),
  );
  const run = query.data;
  return (
    <>
      <QueryState {...query} />
      {run && (
        <>
          <Heading>Planned → actual</Heading>
          <Copy>
            {Math.round(plannedMinutes)} planned min ·{" "}
            {measurement(
              run.duration_min,
              (n) => `${n.toFixed(1)} recorded min`,
            )}
          </Copy>
          <Copy>
            Distance:{" "}
            {measurement(run.distance_km, (n) => `${n.toFixed(2)} km`)}
          </Copy>
          <Copy>
            Average pace:{" "}
            {measurement(
              run.metrics?.average_pace_s_km,
              (n) => `${pace(n)} /km`,
            )}
          </Copy>
          <Copy>
            Average heart rate:{" "}
            {measurement(run.average_hr, (n) => `${Math.round(n)} bpm`)}
          </Copy>
          {run.average_hr == null && (
            <Muted>
              Missing heart-rate measurements do not mean zero training load.
            </Muted>
          )}
          <Heading>Step compliance</Heading>
          {run.step_compliance ? (
            <>
              <Copy>
                {run.step_compliance.score == null
                  ? "Score unavailable"
                  : `${run.step_compliance.score.toFixed(0)}% across scored steps`}{" "}
                · {run.step_compliance.scored_steps} scored ·{" "}
                {run.step_compliance.missing_steps} unavailable
              </Copy>
              <Muted>
                Lap averages estimate target compliance. Missing data is not a
                failed step.
              </Muted>
              {run.step_compliance.steps.map((step) => (
                <Notice
                  key={step.position}
                  title={`${step.position + 1}. ${step.label}`}
                >
                  <Copy>
                    Score:{" "}
                    {step.score == null
                      ? "unavailable"
                      : `${step.score.toFixed(0)}%`}
                  </Copy>
                  <Copy>
                    Duration:{" "}
                    {step.duration_in_range == null
                      ? "unavailable"
                      : step.duration_in_range
                        ? "in range"
                        : "outside range"}{" "}
                    · {Math.round(step.planned_seconds)} planned seconds /{" "}
                    {step.actual_seconds == null
                      ? "unavailable"
                      : Math.round(step.actual_seconds)}{" "}
                    recorded
                  </Copy>
                  <Copy>
                    Target:{" "}
                    {step.target_score == null
                      ? "unavailable"
                      : `${step.target_score.toFixed(0)}% of lap time in range`}
                  </Copy>
                  {step.missing && <Muted>{step.missing}</Muted>}
                </Notice>
              ))}
            </>
          ) : (
            <Muted>
              Step scores unavailable. Sync the matched run to calculate them.
            </Muted>
          )}
          <Heading>Laps</Heading>
          {run.laps == null ? (
            <Muted>Laps unavailable.</Muted>
          ) : run.laps.length === 0 ? (
            <Muted>No laps recorded.</Muted>
          ) : (
            run.laps.map((lap, index) => (
              <Notice
                key={index}
                title={`Lap ${index + 1} · ${measurement(lap.distance_m, (n) => `${(n / 1000).toFixed(2)} km`)} · ${measurement(lap.duration_s, (n) => `${pace(n)} min`)}`}
              >
                <Copy>
                  Average pace:{" "}
                  {measurement(lap.average_pace_s_km, (n) => `${pace(n)} /km`)}{" "}
                  · Average heart rate:{" "}
                  {measurement(lap.average_hr, (n) => `${Math.round(n)} bpm`)}
                </Copy>
              </Notice>
            ))
          )}
        </>
      )}
    </>
  );
}
