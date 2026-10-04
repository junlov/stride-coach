import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react-native";
import * as SecureStore from "expo-secure-store";
import type { Schema } from "../src/api/client";
import { ConnectionProvider } from "../src/state/connection";
import WeekScreen from "../src/screens/week";
import TodayScreen from "../src/screens/today";
import { connection, metrics, mockServer, response, workout } from "./fixtures";

jest.mock("../src/dates", () => ({
  ...jest.requireActual("../src/dates"),
  localDay: () => "2026-10-05",
}));
const detail: Schema<"RunDetail"> = {
  id: "run-123",
  day: workout.day,
  duration_min: 32.5,
  distance_km: 5.25,
  average_hr: 142,
  metrics: { average_pace_s_km: 371.4 },
  laps: [
    {
      duration_s: 371,
      distance_m: 1000,
      average_pace_s_km: 371,
      average_hr: 140,
    },
    {
      duration_s: 372,
      distance_m: 1000,
      average_pace_s_km: 372,
      average_hr: 144,
    },
  ],
};
let server: ReturnType<typeof mockServer>;
beforeEach(() => {
  jest.clearAllMocks();
  jest
    .mocked(SecureStore.getItemAsync)
    .mockResolvedValue(JSON.stringify(connection));
  server = mockServer({
    "/weeks/1": {
      workouts: [{ workout, minutes: 30 }],
      metrics: {
        ...metrics,
        matches: [
          {
            activity_id: detail.id,
            workout_id: workout.id,
            method: "date-kind",
          },
        ],
      },
    },
    "/activities/run-123": detail,
  });
});
const mount = (element = <WeekScreen />) =>
  render(<ConnectionProvider>{element}</ConnectionProvider>);
const openDetail = async () => {
  await fireEvent.press((await screen.findAllByText("Review matched run"))[0]);
};
const activityCalls = () =>
  server.mock.calls.filter(([url]) => String(url).includes("/activities/"));

test.each(["week", "today"])(
  "%s loads captured measurements only when the matched run is opened",
  async (page) => {
    await mount(page === "week" ? <WeekScreen /> : <TodayScreen />);
    await screen.findAllByText("Review matched run");
    expect(activityCalls()).toHaveLength(0);
    await openDetail();
    expect(
      await screen.findByText("30 planned min · 32.5 recorded min"),
    ).toBeTruthy();
    expect(screen.getByText("Distance: 5.25 km")).toBeTruthy();
    expect(screen.getByText("Average pace: 6:11 /km")).toBeTruthy();
    expect(screen.getByText("Average heart rate: 142 bpm")).toBeTruthy();
    expect(screen.getByText("Lap 1 · 1.00 km · 6:11 min")).toBeTruthy();
    expect(screen.getByText("Lap 2 · 1.00 km · 6:12 min")).toBeTruthy();
    expect(
      screen.getByText("Average pace: 6:12 /km · Average heart rate: 144 bpm"),
    ).toBeTruthy();
    expect(screen.getByText(/not confirmed by you/)).toBeTruthy();
    expect(activityCalls()).toHaveLength(1);
    expect(server).toHaveBeenCalledWith(
      `${connection.serverUrl}/activities/run-123`,
      expect.objectContaining({
        method: "GET",
        headers: expect.objectContaining({
          Authorization: `Bearer ${connection.token}`,
        }),
      }),
    );
  },
);

test("partial data preserves recorded summary and laps while marking absent sensors unavailable", async () => {
  await mount();
  await screen.findByText("Review matched run");
  server.mockResolvedValueOnce(
    response({
      ...detail,
      average_hr: null,
      metrics: {},
      laps: [{ duration_s: 120, distance_m: 300 }],
    }),
  );
  await openDetail();
  expect(await screen.findByText("Distance: 5.25 km")).toBeTruthy();
  expect(screen.getByText("Average pace: unavailable")).toBeTruthy();
  expect(screen.getByText("Average heart rate: unavailable")).toBeTruthy();
  expect(screen.getByText("Lap 1 · 0.30 km · 2:00 min")).toBeTruthy();
  expect(
    screen.getByText(
      "Average pace: unavailable · Average heart rate: unavailable",
    ),
  ).toBeTruthy();
  expect(
    screen.getByText(
      /Missing heart-rate measurements do not mean zero training load/,
    ),
  ).toBeTruthy();
});

test.each([null, undefined])(
  "missing optional measurements (%s) remain unavailable",
  async (missing) => {
    await mount();
    await screen.findByText("Review matched run");
    server.mockResolvedValueOnce(
      response({
        ...detail,
        average_hr: missing,
        metrics: missing,
        laps: missing,
      }),
    );
    await openDetail();
    expect(
      await screen.findByText("30 planned min · 32.5 recorded min"),
    ).toBeTruthy();
    expect(screen.getByText("Average pace: unavailable")).toBeTruthy();
    expect(screen.getByText("Average heart rate: unavailable")).toBeTruthy();
    expect(screen.getByText("Laps unavailable.")).toBeTruthy();
  },
);

test("zero measurements and an empty lap list are not treated as missing", async () => {
  await mount();
  await screen.findByText("Review matched run");
  server.mockResolvedValueOnce(
    response({
      ...detail,
      duration_min: 0,
      distance_km: 0,
      average_hr: 0,
      metrics: { average_pace_s_km: 0 },
      laps: [],
    }),
  );
  await openDetail();
  expect(
    await screen.findByText("30 planned min · 0.0 recorded min"),
  ).toBeTruthy();
  expect(screen.getByText("Distance: 0.00 km")).toBeTruthy();
  expect(screen.getByText("Average pace: 0:00 /km")).toBeTruthy();
  expect(screen.getByText("Average heart rate: 0 bpm")).toBeTruthy();
  expect(screen.getByText("No laps recorded.")).toBeTruthy();
});

test("loading is distinct from missing data and closing ignores a late response", async () => {
  await mount();
  await screen.findByText("Review matched run");
  let resolve!: (value: Response) => void;
  server.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  await openDetail();
  expect(screen.getByLabelText("Loading")).toBeTruthy();
  expect(screen.queryByText("Laps unavailable.")).toBeNull();
  await fireEvent.press(screen.getByText("Close run detail"));
  await act(async () => {
    resolve(response({ ...detail, average_hr: 999 }));
  });
  expect(screen.queryByText("Average heart rate: 999 bpm")).toBeNull();
  await openDetail();
  expect(await screen.findByText("Average heart rate: 142 bpm")).toBeTruthy();
});

test.each([404, 401, 503])(
  "activity HTTP %s shows recovery and retry reads the detail",
  async (code) => {
    await mount();
    await screen.findByText("Review matched run");
    server.mockResolvedValueOnce(
      response({ detail: `Activity request failed (${code}).` }, code),
    );
    await openDetail();
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("Laps unavailable.")).toBeNull();
    expect(screen.queryByText("Distance: 5.25 km")).toBeNull();
    if (code === 401) expect(screen.getByText("Open Settings")).toBeTruthy();
    await fireEvent.press(screen.getByText("Retry"));
    expect(await screen.findByText("Distance: 5.25 km")).toBeTruthy();
  },
);

test("step results show failures and missing targets distinctly", async () => {
  await mount();
  await screen.findByText("Review matched run");
  server.mockResolvedValueOnce(
    response({
      ...detail,
      step_compliance: {
        workout_id: workout.id,
        score: 0,
        scored_steps: 1,
        missing_steps: 1,
        steps: [
          {
            position: 0,
            label: "Tempo",
            planned_seconds: 600,
            actual_seconds: 300,
            duration_in_range: false,
            target_score: 0,
            score: 0,
          },
          {
            position: 1,
            label: "Cool down",
            planned_seconds: 600,
            actual_seconds: 600,
            duration_in_range: true,
            target_score: null,
            score: null,
            missing: "Heart rate unavailable.",
          },
        ],
      },
    }),
  );
  await openDetail();
  expect(await screen.findByText("Score: 0%")).toBeTruthy();
  expect(screen.getByText("Score: unavailable")).toBeTruthy();
  expect(screen.getByText("Heart rate unavailable.")).toBeTruthy();
  expect(
    screen.getByText("0% across scored steps · 1 scored · 1 unavailable"),
  ).toBeTruthy();
});
