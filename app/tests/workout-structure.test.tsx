import { render, screen } from "@testing-library/react-native";
import { WorkoutCard, workoutMinutes } from "../src/components/workout";
import { GarminPayload } from "../src/components/garmin-payload";
import { workout } from "./fixtures";
import type { Schema } from "../src/api/client";

const structured: Schema<"Workout"> = {
  ...workout,
  kind: "intervals",
  steps: [
    { label: "Warm up", minutes: 10, end_condition: "lap", hr_zone: 2 },
    { label: "Intervals", repetitions: 6, skip_last_rest: true, steps: [
      { label: "Run", minutes: 3.6, distance_m: 800, end_condition: "distance", pace_min: 270, pace_max: 290, cadence_min: 162, cadence_max: 182 },
      { label: "Jog", minutes: 3, distance_m: 400, end_condition: "distance", hr_zone: 1 },
    ] },
    { label: "Cool down", minutes: 10, end_condition: "lap", hr_zone: 2 },
  ],
};

test("workout card shows repeats, distance, zones, Lap and secondary cadence", async () => {
  await render(<WorkoutCard workout={structured} />);
  expect(screen.getByText(/6 x \(Run: 800 m · 4:30 to 4:50 \/km · 162 to 182 spm; Jog: 400 m · Zone 1\)/)).toBeTruthy();
  expect(screen.getByText(/Warm up: press Lap \(10.0 min estimated\) · Zone 2/)).toBeTruthy();
  expect(screen.getByText(/Skip last recovery/)).toBeTruthy();
  expect(workoutMinutes(structured)).toBeCloseTo(56.6);
});

test("push preview reads the actual repeat payload including cadence and Lap", async () => {
  await render(<GarminPayload payload={{ workoutName: "Intervals", workoutSegments: [{ workoutSteps: [
    { description: "Warm up", endCondition: { conditionTypeKey: "lap.button" }, targetType: { workoutTargetTypeKey: "heart.rate.zone" }, zoneNumber: 2 },
    { type: "RepeatGroupDTO", numberOfIterations: 6, skipLastRestStep: true, workoutSteps: [
      { description: "Run", endCondition: { conditionTypeKey: "distance" }, endConditionValue: 800,
        targetType: { workoutTargetTypeKey: "pace.zone" }, targetValueOne: 1000 / 290, targetValueTwo: 1000 / 270,
        secondaryTargetType: { workoutTargetTypeKey: "cadence" }, secondaryTargetValueOne: 162, secondaryTargetValueTwo: 182 },
      { description: "Jog", endCondition: { conditionTypeKey: "distance" }, endConditionValue: 400,
        targetType: { workoutTargetTypeKey: "heart.rate.zone" }, zoneNumber: 1 },
    ] },
  ] }] }} />);
  expect(screen.getByText(/Warm up: press Lap · Zone 2/)).toBeTruthy();
  expect(screen.getByText(/6 x .*Run: 800 m · 4:30 to 4:50 \/km · 162 to 182 spm.*Jog: 400 m · Zone 1.*Skip last recovery/)).toBeTruthy();
});
