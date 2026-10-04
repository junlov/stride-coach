import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react-native";
import * as SecureStore from "expo-secure-store";
import { useColorScheme } from "react-native";
import { ConnectionProvider } from "../src/state/connection";
import { Page, Copy } from "../src/components/ui";
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

test("seven days distinguish planned rest from an inferred match, without inventing actual measurements", async () => {
  server = mockServer({
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
  await fireEvent.press(screen.getByText("Review matched run"));
  expect(screen.getByText("Activity: run-123")).toBeTruthy();
  expect(screen.getByText("Match method: date-kind")).toBeTruthy();
  expect(screen.getByText(/recorded duration unavailable/)).toBeTruthy();
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
  await fireEvent.press(screen.getByText("Why this workout?"));
  expect(screen.getByText(/personalized reason.*not available/)).toBeTruthy();
});

test("J2 Today links to a week-scoped Garmin preview", async () => {
  await mount(<TodayScreen />);
  const link = await screen.findByText("Send this week to Garmin");
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
  server.mockResolvedValueOnce(response({}, 401));
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
