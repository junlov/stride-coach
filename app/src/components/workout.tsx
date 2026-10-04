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
    ? step.repetitions *
        step.steps.reduce((sum, child) => sum + child.minutes, 0) -
        (step.skip_last_rest ? step.steps[step.steps.length - 1].minutes : 0)
    : step.minutes;
}
export const workoutMinutes = (workout: Schema<"WorkoutSummary">) =>
  workout.steps.reduce((sum, step) => sum + stepMinutes(step), 0);
export function WorkoutCard({
  workout,
  hero = false,
  match,
  children,
}: {
  workout: Schema<"WorkoutSummary">;
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
        {workout.day} · {workout.name}
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
      {workout.steps.map((_, i) => (
        <Muted key={i}>{workout.step_descriptions[i]}</Muted>
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
