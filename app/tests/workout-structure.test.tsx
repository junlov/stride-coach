import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react-native";
import { WorkoutCard, workoutMinutes } from "../src/components/workout";
import { GarminPayload } from "../src/components/garmin-payload";
import { workout } from "./fixtures";
import type { Schema } from "../src/api/client";

const structured: Schema<"WorkoutSummary"> = {
  ...workout,
  kind: "intervals",
  name: "Reps 6x800 m",
  step_descriptions: [
    "Warm up easy; press Lap (10 min estimated) at Zone 2. Start gently.",
    "6 x (800 m at 4:30 to 4:50 /km; 162 to 182 spm. Finish smooth.; 400 m easy jog at Zone 1. Relax your shoulders.) Skip last recovery.",
    "Cool down; press Lap (10 min estimated) at Zone 2. Let breathing settle.",
  ],
  steps: [
    { label: "Warm up", minutes: 10, end_condition: "lap", hr_zone: 2 },
    {
      label: "Intervals",
      repetitions: 6,
      skip_last_rest: true,
      steps: [
        {
          label: "Run",
          minutes: 3.6,
          distance_m: 800,
          end_condition: "distance",
          pace_min: 270,
          pace_max: 290,
          cadence_min: 162,
          cadence_max: 182,
        },
        {
          label: "Jog",
          minutes: 3,
          distance_m: 400,
          end_condition: "distance",
          hr_zone: 1,
        },
      ],
    },
    { label: "Cool down", minutes: 10, end_condition: "lap", hr_zone: 2 },
  ],
};

test("workout card shows repeats, distance, zones, Lap and secondary cadence", async () => {
  await render(<WorkoutCard workout={structured} />);
  expect(
    screen.getByText(
      /6 x .*800 m at 4:30 to 4:50 \/km; 162 to 182 spm.*400 m easy jog at Zone 1/,
    ),
  ).toBeTruthy();
  expect(
    screen.getByText(/Warm up easy; press Lap \(10 min estimated\) at Zone 2/),
  ).toBeTruthy();
  expect(screen.getByText(/Skip last recovery/)).toBeTruthy();
  expect(workoutMinutes(structured)).toBeCloseTo(56.6);
  const graph = screen.getByRole("image");
  expect(graph.props.accessibilityLabel.match(/Run/g)).toHaveLength(6);
  expect(graph.props.accessibilityLabel.match(/Jog/g)).toHaveLength(5);
});

test("push preview reads the actual repeat payload including cadence and Lap", async () => {
  await render(
    <GarminPayload
      payload={{
        workoutName: "Intervals",
        workoutSegments: [
          {
            workoutSteps: [
              {
                description: "Warm up",
                endCondition: { conditionTypeKey: "lap.button" },
                targetType: { workoutTargetTypeKey: "heart.rate.zone" },
                zoneNumber: 2,
              },
              {
                type: "RepeatGroupDTO",
                numberOfIterations: 6,
                skipLastRestStep: true,
                workoutSteps: [
                  {
                    description: "Run",
                    endCondition: { conditionTypeKey: "distance" },
                    endConditionValue: 800,
                    targetType: { workoutTargetTypeKey: "pace.zone" },
                    targetValueOne: 1000 / 290,
                    targetValueTwo: 1000 / 270,
                    secondaryTargetType: { workoutTargetTypeKey: "cadence" },
                    secondaryTargetValueOne: 162,
                    secondaryTargetValueTwo: 182,
                  },
                  {
                    description: "Jog",
                    endCondition: { conditionTypeKey: "distance" },
                    endConditionValue: 400,
                    targetType: { workoutTargetTypeKey: "heart.rate.zone" },
                    zoneNumber: 1,
                  },
                ],
              },
            ],
          },
        ],
      }}
    />,
  );
  expect(screen.getByText(/Warm up: press Lap · Zone 2/)).toBeTruthy();
  expect(
    screen.getByText(
      /6 x .*Run: 800 m · 4:30 to 4:50 \/km · 162 to 182 spm.*Jog: 400 m · Zone 1.*Skip last recovery/,
    ),
  ).toBeTruthy();
});

test("daily preview renders the actual HTTP response before and after workouts", async () => {
  const proposal: Schema<"DailyProposalView"> = JSON.parse(
    execFileSync(
      resolve(__dirname, "../../.venv/bin/python"),
      [resolve(__dirname, "daily_proposal_response.py")],
      { encoding: "utf8" },
    ),
  );
  expect(proposal.before).toBeTruthy();
  expect(proposal.after).toBeTruthy();
  await render(
    <>
      <WorkoutCard workout={proposal.before!} />
      <WorkoutCard workout={proposal.after!} />
    </>,
  );
  for (const workout of [proposal.before!, proposal.after!]) {
    expect(workout.step_descriptions.length).toBe(workout.steps.length);
    for (const description of workout.step_descriptions) {
      expect(screen.getAllByText(description).length).toBeGreaterThan(0);
    }
  }
  expect(screen.getAllByRole("image")).toHaveLength(2);
  expect(screen.getByText(/Strides: 4 x/)).toBeTruthy();
});
