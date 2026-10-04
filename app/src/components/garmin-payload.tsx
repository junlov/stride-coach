import { useState } from "react";
import { Button, Copy, Heading } from "./ui";
import { pace } from "./workout";

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function stepSummary(value: unknown, index: number): string {
  const step = record(value);
  if (step.type === "RepeatGroupDTO" && Array.isArray(step.workoutSteps)) {
    return `${index + 1}. ${step.numberOfIterations} x (${step.workoutSteps.map(stepSummary).join("; ")})${step.skipLastRestStep ? " · Skip last recovery" : ""}`;
  }
  const label =
    typeof step.description === "string"
      ? step.description
      : `Step ${index + 1}`;
  const condition = record(step.endCondition).conditionTypeKey;
  const amount = step.endConditionValue;
  const duration =
    condition === "lap.button" ? "press Lap" :
    typeof amount === "number" && Number.isFinite(amount)
      ? condition === "time"
        ? `${amount / 60} min`
        : condition === "distance"
          ? `${amount} m`
          : "Duration unavailable"
      : "Duration unavailable";
  const target = record(step.targetType).workoutTargetTypeKey;
  const low = step.targetValueOne;
  const high = step.targetValueTwo;
  let targetText = "Target unavailable";
  if (
    typeof low === "number" &&
    typeof high === "number" &&
    Number.isFinite(low) &&
    Number.isFinite(high)
  ) {
    if (target === "pace.zone" && low > 0 && high > 0)
      targetText = `${pace(1000 / high)} to ${pace(1000 / low)} /km`;
    else if (target === "heart.rate.zone") targetText = `${low} to ${high} bpm`;
  }
  if (target === "heart.rate.zone" && typeof step.zoneNumber === "number") {
    targetText = `Zone ${step.zoneNumber}`;
  }
  const cadence = record(step.secondaryTargetType).workoutTargetTypeKey === "cadence"
    && typeof step.secondaryTargetValueOne === "number" && typeof step.secondaryTargetValueTwo === "number"
    ? ` · ${step.secondaryTargetValueOne} to ${step.secondaryTargetValueTwo} spm` : "";
  return `${index + 1}. ${label}: ${duration} · ${targetText}${cadence}`;
}

export function GarminPayload({
  payload,
}: {
  payload: Record<string, unknown>;
}) {
  const [details, setDetails] = useState(false);
  const segments = Array.isArray(payload.workoutSegments)
    ? payload.workoutSegments
    : [];
  const steps = segments.flatMap((segment) => {
    const values = record(segment).workoutSteps;
    return Array.isArray(values) ? values : [];
  });
  return (
    <>
      <Heading>
        {typeof payload.workoutName === "string"
          ? payload.workoutName
          : "Workout"}
      </Heading>
      {steps.map((step, index) => (
        <Copy key={index}>{stepSummary(step, index)}</Copy>
      ))}
      {steps.length === 0 && (
        <Copy>
          Workout steps unavailable. Read the payload details before confirming.
        </Copy>
      )}
      <Button
        variant="secondary"
        label={details ? "Hide payload details" : "Show payload details"}
        onPress={() => setDetails(!details)}
      />
      {details && <Copy>{JSON.stringify(payload, null, 2)}</Copy>}
    </>
  );
}
