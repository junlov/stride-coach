import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react-native";
import * as SecureStore from "expo-secure-store";
import { useColorScheme } from "react-native";
import { ConnectionProvider, useConnection } from "../src/state/connection";
import { Page, Copy, Button } from "../src/components/ui";
import { palettes } from "../src/theme";
import WeekScreen from "../src/screens/week";
import ActionsScreen from "../src/screens/actions";
import TodayScreen from "../src/screens/today";
import PlanScreen from "../src/screens/plan";
import InsightsScreen from "../src/screens/insights";
import {
  adjustment,
  connection,
  metrics,
  mockServer,
  plan,
  response,
  status,
  workout,
} from "./fixtures";
jest.mock("../src/dates", () => ({
  ...jest.requireActual("../src/dates"),
  localDay: () => "2026-10-05",
}));
jest.mock("react-native/Libraries/Utilities/useColorScheme", () => ({
  __esModule: true,
  default: jest.fn(() => "light"),
}));
let server: ReturnType<typeof mockServer>;
beforeEach(() => {
  jest.clearAllMocks();
  jest
    .mocked(SecureStore.getItemAsync)
    .mockResolvedValue(JSON.stringify(connection));
  jest.mocked(useColorScheme).mockReturnValue("light");
  server = mockServer();
});
const mount = (element: React.ReactElement) =>
  render(<ConnectionProvider>{element}</ConnectionProvider>);
const writes = (path: string) =>
  server.mock.calls.filter(([url]) => String(url).endsWith(path));

test("seven days distinguish planned rest from an inferred match with recorded measurements", async () => {
  server = mockServer({
    "/activities/run-123": {
      id: "run-123",
      day: workout.day,
      duration_min: 32.5,
      distance_km: 5.25,
    },
    "/weeks/1": {
      workouts: [{ workout, minutes: 30 }],
      metrics: {
        ...metrics,
        matches: [
          {
            activity_id: "run-123",
            workout_id: workout.id,
            method: "date-kind",
          },
        ],
      },
    },
  });
  await mount(<WeekScreen />);
  expect(await screen.findAllByText("Rest planned")).toHaveLength(6);
  expect(
    screen.getAllByText(`${workout.day} · ${workout.name}`).length,
  ).toBeGreaterThan(0);
  await fireEvent.press(screen.getByText("Review matched run"));
  expect(screen.getByText("Activity: run-123")).toBeTruthy();
  expect(screen.getByText("Match method: date-kind")).toBeTruthy();
  expect(
    await screen.findByText("30 planned min · 32.5 recorded min"),
  ).toBeTruthy();
  expect(screen.getByText(/not confirmed by you/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Previous week" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Next week" })).toBeDisabled();
});

test("week navigation requests the selected week and handles no weeks", async () => {
  server = mockServer({
    "/status": { ...status, weeks: [metrics, { ...metrics, week: 2 }] },
    "/weeks/2": { workouts: [], metrics: { ...metrics, week: 2 } },
  });
  const view = await mount(<WeekScreen />);
  await fireEvent.press(await screen.findByText("Next week"));
  await waitFor(() => expect(writes("/weeks/2")).toHaveLength(1));
  expect(await screen.findAllByText("Rest planned")).toHaveLength(7);
  await view.unmount();
  server = mockServer({ "/status": { ...status, weeks: [] } });
  await mount(<WeekScreen />);
  expect(await screen.findByText("No training weeks yet.")).toBeTruthy();
  expect(writes("/weeks/undefined")).toHaveLength(0);
});

test("workout explanations disclose when personalized reasons are absent", async () => {
  await mount(<PlanScreen />);
  await fireEvent.press(await screen.findByText("View week 1"));
  expect(
    screen.getAllByText(`${workout.day} · ${workout.name}`).length,
  ).toBeGreaterThan(0);
  await fireEvent.press(screen.getByText("Why this workout?"));
  expect(screen.getByText(/personalized reason.*not available/)).toBeTruthy();
});

test("J2 Today links to a week-scoped Garmin preview", async () => {
  await mount(<TodayScreen />);
  const link = await screen.findByText("Send this week to Garmin");
  expect(
    screen.getAllByText(`${workout.day} · ${workout.name}`).length,
  ).toBeGreaterThan(0);
  expect(link.props.href).toEqual({
    pathname: "/actions",
    params: { week: "1" },
  });
});

test("J3 saved applied adjustments show the server reasons and Garmin boundary", async () => {
  server = mockServer({
    "/status": { ...status, adjustments: [{ ...adjustment, applied: true }] },
  });
  await mount(<PlanScreen />);
  expect(await screen.findByText("Week 2 · Applied")).toBeTruthy();
  expect(screen.getByText("Reduce volume after missed sessions.")).toBeTruthy();
  expect(
    screen.getByText(/Adjusting the plan does not send Garmin workouts/),
  ).toBeTruthy();
});

test("progress chart exposes real totals to screen readers and missing load is not zero", async () => {
  await mount(<InsightsScreen />);
  expect(
    await screen.findByLabelText(
      "Week 1: 60 planned minutes, 30 recorded minutes",
    ),
  ).toBeTruthy();
  expect(
    screen.getByText(/heart-rate load is unavailable, not zero/),
  ).toBeTruthy();
});

test.each(["push", "remove"])(
  "uncertain %s cannot retry until a read and explicit acknowledgement, then requires a fresh preview",
  async (action) => {
    await mount(<ActionsScreen />);
    const preview =
      action === "push" ? "Preview Garmin push" : "Preview Garmin removal";
    const confirm =
      action === "push"
        ? "Confirm live Garmin push"
        : "Confirm live Garmin removal";
    await fireEvent.press(await screen.findByText(preview));
    await screen.findByText(confirm);
    server
      .mockResolvedValueOnce(response({ connected: true }))
      .mockRejectedValueOnce(new Error("timeout"));
    await fireEvent.press(screen.getByText(confirm));
    expect(await screen.findByText("The result is unknown.")).toBeTruthy();
    expect(writes(`/${action}`)).toHaveLength(2);
    expect(screen.getByRole("button", { name: preview })).toBeDisabled();
    expect(screen.queryByText(confirm)).toBeNull();
    server.mockRejectedValueOnce(new Error("still offline"));
    await fireEvent.press(screen.getByText("Inspect current state"));
    expect(await screen.findByText(/Cannot reach your server/)).toBeTruthy();
    expect(screen.queryByText("I checked the current state")).toBeNull();
    await fireEvent.press(screen.getByText("Inspect current state"));
    await fireEvent.press(
      await screen.findByText("I checked the current state"),
    );
    expect(writes(`/${action}`)).toHaveLength(2);
    expect(screen.queryByText(confirm)).toBeNull();
    await fireEvent.press(screen.getByText(preview));
    expect(await screen.findByText(confirm)).toBeTruthy();
    expect(
      JSON.parse(
        (writes(`/${action}`).at(-1) as unknown as [string, RequestInit])[1]
          .body as string,
      ),
    ).toMatchObject({ dry_run: true, apply: false });
  },
);

test("an explicit adjustment rejection displays eligibility and cannot apply a stale proposal", async () => {
  await mount(<ActionsScreen />);
  await fireEvent.changeText(
    await screen.findByLabelText("Week (blank pushes all future weeks)"),
    "2",
  );
  await fireEvent.press(screen.getByText("Preview adjustment"));
  await screen.findByText("Confirm adjustment");
  server.mockResolvedValueOnce(
    response({ detail: "Sync must cover two complete weeks." }, 409),
  );
  await fireEvent.press(screen.getByText("Confirm adjustment"));
  expect(await screen.findByText("Not ready to adjust yet.")).toBeTruthy();
  expect(screen.queryByText("The result is unknown.")).toBeNull();
  expect(screen.queryByText("Confirm adjustment")).toBeNull();
});

test("expired authentication shows Settings recovery with no cached workout", async () => {
  const original = server.getMockImplementation()!;
  server.mockImplementation(async (input) =>
    new URL(String(input)).pathname === "/status"
      ? response({}, 401)
      : original(input),
  );
  await mount(<TodayScreen />);
  expect(
    await screen.findByText("Your connection needs attention."),
  ).toBeTruthy();
  expect(screen.getByText("Open Settings")).toBeTruthy();
  expect(screen.queryByText(/Easy running: 30/)).toBeNull();
});

test.each(["light", "dark"] as const)(
  "shared runner primitives follow %s appearance",
  async (scheme) => {
    jest.mocked(useColorScheme).mockReturnValue(scheme);
    await render(
      <Page title="Theme proof">
        <Copy>Readable content</Copy>
      </Page>,
    );
    expect(screen.getByText("Theme proof")).toHaveStyle({
      color: palettes[scheme].text,
    });
    expect(screen.getByText("Readable content")).toHaveStyle({
      color: palettes[scheme].text,
    });
  },
);

test("the API's empty push rejection becomes an empty state without confirmation", async () => {
  await mount(<ActionsScreen />);
  server.mockResolvedValueOnce(
    response({ detail: "No future workouts match this selection" }, 400),
  );
  await fireEvent.press(await screen.findByText("Preview Garmin push"));
  expect(await screen.findByText("Nothing to send.")).toBeTruthy();
  expect(screen.queryByText("Confirm live Garmin push")).toBeNull();
});

function ConnectionControls() {
  const { save, clear, refresh } = useConnection();
  return (
    <>
      <Button
        label="Switch server"
        onPress={() =>
          void save({ ...connection, serverUrl: "https://second.example.test" })
        }
      />
      <Button label="Forget server" onPress={() => void clear()} />
      <Button label="Refresh plan" onPress={refresh} />
    </>
  );
}

test("recovery inspection and acknowledgement reset when a connection is forgotten", async () => {
  await mount(
    <>
      <ActionsScreen />
      <ConnectionControls />
    </>,
  );
  await fireEvent.press(await screen.findByText("Preview Garmin push"));
  await screen.findByText("Confirm live Garmin push");
  server
    .mockResolvedValueOnce(response({ connected: true }))
    .mockRejectedValueOnce(new Error("timeout"));
  await fireEvent.press(screen.getByText("Confirm live Garmin push"));
  await fireEvent.press(await screen.findByText("Inspect current state"));
  await screen.findByText("I checked the current state");
  await fireEvent.press(screen.getByText("Forget server"));
  await fireEvent.press(screen.getByText("Switch server"));
  expect(screen.queryByText("I checked the current state")).toBeNull();
  expect(screen.queryByText("Current server state")).toBeNull();
  expect(screen.queryByText("The result is unknown.")).toBeNull();
  expect(
    screen.getByRole("button", { name: "Preview Garmin push" }),
  ).toBeEnabled();
});

test("a late failed write from the old connection cannot block the new connection", async () => {
  await mount(
    <>
      <ActionsScreen />
      <ConnectionControls />
    </>,
  );
  await fireEvent.press(await screen.findByText("Preview Garmin push"));
  await screen.findByText("Confirm live Garmin push");
  let reject!: (error: Error) => void;
  server
    .mockResolvedValueOnce(response({ connected: true }))
    .mockImplementationOnce(
      () =>
        new Promise<Response>((_, fail) => {
          reject = fail;
        }),
    );
  await fireEvent.press(screen.getByText("Confirm live Garmin push"));
  await waitFor(() => expect(reject).toBeDefined());
  await fireEvent.press(screen.getByText("Switch server"));
  await act(async () => {
    reject(new Error("timeout"));
  });
  expect(screen.queryByText("The result is unknown.")).toBeNull();
  expect(
    screen.getByRole("button", { name: "Preview Garmin push" }),
  ).toBeEnabled();
});

test("week selection resets across connections and falls back when the plan loses a week", async () => {
  server = mockServer({
    "/status": { ...status, weeks: [metrics, { ...metrics, week: 2 }] },
    "/weeks/2": { workouts: [], metrics: { ...metrics, week: 2 } },
  });
  await mount(
    <>
      <WeekScreen />
      <ConnectionControls />
    </>,
  );
  await fireEvent.press(await screen.findByText("Next week"));
  await screen.findByText("Week 2");
  await fireEvent.press(screen.getByText("Switch server"));
  await screen.findByText("Week 1");
  await fireEvent.press(screen.getByText("Next week"));
  await screen.findByText("Week 2");
  server.mockClear();
  server
    .mockResolvedValueOnce(response(plan))
    .mockResolvedValueOnce(response(status));
  await fireEvent.press(screen.getByText("Refresh plan"));
  await screen.findByText("Week 1");
  expect(writes("/weeks/2")).toHaveLength(0);
  expect(screen.getByRole("button", { name: "Next week" })).toBeDisabled();
});

test("push preview shows workout content, converts pace, and keeps raw details optional", async () => {
  const payload = {
    workoutName: "Easy Run 30 min",
    workoutSegments: [
      {
        workoutSteps: [
          {
            description: "Warm up",
            endCondition: { conditionTypeKey: "time" },
            endConditionValue: 600,
            targetType: { workoutTargetTypeKey: "heart.rate.zone" },
            targetValueOne: 120,
            targetValueTwo: 140,
          },
          {
            description: "Run",
            endCondition: { conditionTypeKey: "distance" },
            endConditionValue: 1000,
            targetType: { workoutTargetTypeKey: "pace.zone" },
            targetValueOne: 1000 / 360,
            targetValueTwo: 1000 / 300,
          },
        ],
      },
    ],
  };
  server = mockServer({
    "/push": [{ action: "preview", date: "2026-10-05", payload }],
  });
  await mount(<ActionsScreen />);
  await fireEvent.press(await screen.findByText("Preview Garmin push"));
  await screen.findByText("Easy Run 30 min");
  expect(screen.getByText("2026-10-05")).toBeTruthy();
  expect(screen.getByText("1. Warm up: 10 min · 120 to 140 bpm")).toBeTruthy();
  expect(screen.getByText("2. Run: 1000 m · 5:00 to 6:00 /km")).toBeTruthy();
  expect(screen.queryByText(JSON.stringify(payload, null, 2))).toBeNull();
  await fireEvent.press(screen.getByText("Show payload details"));
  expect(screen.getByText(JSON.stringify(payload, null, 2))).toBeTruthy();
  await fireEvent.press(screen.getByText("Hide payload details"));
  expect(screen.queryByText(JSON.stringify(payload, null, 2))).toBeNull();
});

test("removal preview counts ownership candidates rather than remote workouts", async () => {
  server = mockServer({
    "/remove": [
      { action: "preview-remove", ownership_tag: "stride-coach:synthetic" },
    ],
  });
  await mount(<ActionsScreen />);
  await fireEvent.press(await screen.findByText("Preview Garmin removal"));
  expect(
    await screen.findByText(
      "Remove Garmin matches for 1 ownership candidates?",
    ),
  ).toBeTruthy();
  expect(screen.getByText(/never uploaded/)).toBeTruthy();
});

test("a late inspection cannot populate recovery state on the new server", async () => {
  await mount(
    <>
      <ActionsScreen />
      <ConnectionControls />
    </>,
  );
  await fireEvent.press(await screen.findByText("Preview Garmin push"));
  await screen.findByText("Confirm live Garmin push");
  server
    .mockResolvedValueOnce(response({ connected: true }))
    .mockRejectedValueOnce(new Error("timeout"));
  await fireEvent.press(screen.getByText("Confirm live Garmin push"));
  await screen.findByText("Inspect current state");
  let resolve!: (value: Response) => void;
  server.mockImplementationOnce(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  await fireEvent.press(screen.getByText("Inspect current state"));
  await waitFor(() => expect(resolve).toBeDefined());
  await fireEvent.press(screen.getByText("Switch server"));
  await act(async () => {
    resolve(response({ ...status, scheduled_workouts: 99 }));
  });
  expect(screen.queryByText("Current server state")).toBeNull();
  expect(screen.queryByText("I checked the current state")).toBeNull();
  expect(
    screen.getByRole("button", { name: "Preview Garmin push" }),
  ).toBeEnabled();
});
