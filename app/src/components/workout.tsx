import { ReactNode, useState } from "react";
import { Schema } from "../api/client";
import { Badge, Button, Card, Copy, Heading, Hero, Muted, Notice } from "./ui";
export function pace(seconds: number) {
  const rounded = Math.round(seconds);
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, "0")}`;
}
export const workoutMinutes = (workout: Schema<"Workout">) =>
  workout.steps.reduce((sum, step) => sum + step.minutes, 0);
export function WorkoutCard({
  workout,
  hero = false,
  match,
  children,
}: {
  workout: Schema<"Workout">;
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
        {workout.day} · {workout.kind}
      </Heading>
      {hero ? (
        <Hero value={Math.round(workoutMinutes(workout))} unit="min" />
      ) : (
        <Copy>
          {Math.round(workoutMinutes(workout))} min · {workout.phase}
          {workout.cutback ? " · Cutback" : ""}
        </Copy>
      )}
      {workout.steps.map((step, i) => (
        <Muted key={i}>
          {step.label}: {step.minutes.toFixed(1)} min
          {step.pace_min && step.pace_max
            ? ` · ${pace(step.pace_min)} to ${pace(step.pace_max)} /km`
            : ""}
          {step.hr_min && step.hr_max
            ? ` · ${step.hr_min} to ${step.hr_max} bpm`
            : ""}
        </Muted>
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
              <Heading>Planned → actual</Heading>
              <Copy>
                {Math.round(workoutMinutes(workout))} planned min · recorded
                duration unavailable
              </Copy>
              <Muted>
                Recorded pace, distance, heart rate, laps, route and activity
                source are not available in this response. Missing heart-rate
                measurements do not mean zero training load.
              </Muted>
            </Notice>
          )}
        </>
      )}
    </Card>
  );
}
