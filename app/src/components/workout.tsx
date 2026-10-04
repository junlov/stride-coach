import { Schema } from "../api/client";
import { Card, Copy, Heading, Muted } from "./ui";
function pace(seconds: number) {
  const rounded = Math.round(seconds);
  return `${Math.floor(rounded / 60)}:${String(rounded % 60).padStart(2, "0")}`;
}
export function WorkoutCard({ workout }: { workout: Schema<"Workout"> }) {
  return (
    <Card>
      <Heading>
        {workout.day} · {workout.kind}
      </Heading>
      <Copy>
        {Math.round(workout.steps.reduce((sum, step) => sum + step.minutes, 0))}{" "}
        min · {workout.phase}
        {workout.cutback ? " · Cutback" : ""}
      </Copy>
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
    </Card>
  );
}
