import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react-native";
import * as SecureStore from "expo-secure-store";
import { ConnectionProvider } from "../src/state/connection";
import ActionsScreen from "../src/screens/actions";
import ActionsRoute from "../src/app/actions";
import SettingsScreen from "../src/screens/settings";
import TodayScreen from "../src/screens/today";
import PlanScreen from "../src/screens/plan";
import InsightsScreen from "../src/screens/insights";
import GoalScreen from "../src/screens/goal";
import { connection, mockServer, plan, response } from "./fixtures";

jest.mock("../src/dates", () => ({
  ...jest.requireActual("../src/dates"),
  localDay: () => "2026-10-05",
}));
let server: ReturnType<typeof mockServer>;
beforeEach(() => {
  jest.clearAllMocks();
  jest
    .mocked(SecureStore.getItemAsync)
    .mockResolvedValue(JSON.stringify(connection));
  jest.mocked(SecureStore.setItemAsync).mockResolvedValue();
  jest.mocked(SecureStore.deleteItemAsync).mockResolvedValue();
  server = mockServer();
});
async function mount(component: React.ReactElement) {
  await render(<ConnectionProvider>{component}</ConnectionProvider>);
  await waitFor(() => expect(SecureStore.getItemAsync).toHaveBeenCalled());
}
function bodies(path: string) {
  return (server as jest.Mock).mock.calls
    .filter(([url]) => url.endsWith(path))
    .map(([, init]) => JSON.parse(init.body));
}
test("today shows the local workout and current week", async () => {
  await mount(<TodayScreen />);
  expect(await screen.findByText("Week 1")).toBeTruthy();
  expect(screen.getAllByText(/Easy running: 30.0 min/)).toHaveLength(2);
  expect(server).toHaveBeenCalledWith(
    `${connection.serverUrl}/weeks/1`,
    expect.anything(),
  );
});
test("before the plan starts, shows its start date without requesting a nonexistent week", async () => {
  server = mockServer({
    "/plan": { ...plan, setup: { ...plan.setup, start: "2026-10-12" } },
  });
  await mount(<TodayScreen />);
  expect(await screen.findByText("Your plan starts 2026-10-12.")).toBeTruthy();
  expect(
    (server as jest.Mock).mock.calls.some(([url]) => url.includes("/weeks/")),
  ).toBe(false);
});
test("read screens recover after an offline response", async () => {
  server.mockRejectedValueOnce(new Error("offline"));
  await mount(<TodayScreen />);
  expect(await screen.findByText(/Cannot reach your server/)).toBeTruthy();
  await fireEvent.press(screen.getByText("Retry"));
  expect(await screen.findByText("Week 1")).toBeTruthy();
});
test("plan expands workouts and progress shows incomplete heart-rate load", async () => {
  const view = await render(
    <ConnectionProvider>
      <PlanScreen />
      <InsightsScreen />
    </ConnectionProvider>,
  );
  await fireEvent.press(await screen.findByText("View week 1"));
  expect(screen.getByText(/Easy running: 30.0 min/)).toBeTruthy();
  expect(await screen.findByText("Training load: 24.0 TRIMP")).toBeTruthy();
  expect(
    screen.getByText("1 runs missing heart rate. Load is incomplete."),
  ).toBeTruthy();
  await view.unmount();
});
test.each(["push", "remove"] as const)(
  "%s requires server preview and explicit confirmation",
  async (action) => {
    await mount(<ActionsScreen />);
    await fireEvent.press(
      await screen.findByText(
        action === "push" ? "Preview Garmin push" : "Preview Garmin removal",
      ),
    );
    const label =
      action === "push"
        ? "Confirm live Garmin push"
        : "Confirm live Garmin removal";
    expect(await screen.findByText("Garmin dry-run preview")).toBeTruthy();
    expect(bodies(`/${action}`)).toEqual([{ dry_run: true, apply: false }]);
    await fireEvent.press(screen.getByText(label));
    await waitFor(() =>
      expect(bodies(`/${action}`)).toEqual([
        { dry_run: true, apply: false },
        { dry_run: false, apply: true },
      ]),
    );
    expect(
      await screen.findByText(
        "Server action completed. Review each result below.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(label)).toBeNull();
  },
);
test("changing week invalidates preview and cancellation never applies", async () => {
  await mount(<ActionsScreen />);
  await fireEvent.changeText(
    await screen.findByLabelText("Week (blank pushes all future weeks)"),
    "2",
  );
  await fireEvent.press(screen.getByText("Preview Garmin push"));
  await screen.findByText("Confirm live Garmin push");
  expect(bodies("/push")).toEqual([{ week: 2, dry_run: true, apply: false }]);
  await fireEvent.changeText(
    screen.getByLabelText("Week (blank pushes all future weeks)"),
    "3",
  );
  expect(screen.queryByText("Confirm live Garmin push")).toBeNull();
  await fireEvent.press(screen.getByText("Preview Garmin push"));
  await screen.findByText("Confirm live Garmin push");
  await fireEvent.press(screen.getByText("Cancel preview"));
  expect(bodies("/push").every((body) => body.apply === false)).toBe(true);
});
test("failed preview cannot be confirmed and displays authentication failure", async () => {
  await mount(<ActionsScreen />);
  server.mockResolvedValueOnce(response({}, 401));
  await fireEvent.press(await screen.findByText("Preview Garmin push"));
  expect(await screen.findByText(/Authentication failed/)).toBeTruthy();
  expect(screen.queryByText("Confirm live Garmin push")).toBeNull();
});
test("adapt shows reasons before applying and sync reports results", async () => {
  await mount(<ActionsScreen />);
  await fireEvent.changeText(
    await screen.findByLabelText("Week (blank pushes all future weeks)"),
    "2",
  );
  await fireEvent.press(screen.getByText("Preview adjustment"));
  expect(
    await screen.findByText("Reduce volume after missed sessions."),
  ).toBeTruthy();
  expect(bodies("/adapt")).toEqual([]);
  await fireEvent.press(screen.getByText("Confirm adjustment"));
  await waitFor(() =>
    expect(bodies("/adapt")).toEqual([{ week: 2, apply: true }]),
  );
  await screen.findByText(/Week 2 adjustment applied/);
  await fireEvent.press(screen.getByText("Sync activities"));
  expect(
    await screen.findByText(
      "Synced 1 activities from 2026-09-07 through 2026-10-05.",
    ),
  ).toBeTruthy();
});
test("settings test uses unsaved values, saves securely, and can forget them", async () => {
  await mount(<SettingsScreen />);
  await waitFor(() =>
    expect(screen.getByLabelText("Server URL").props.value).toBe(
      connection.serverUrl,
    ),
  );
  await fireEvent.changeText(
    screen.getByLabelText("Server URL"),
    "https://other.example.test",
  );
  await fireEvent.press(screen.getByText("Test connection"));
  expect(
    await screen.findByText(
      "Connected. Authentication and status are working.",
    ),
  ).toBeTruthy();
  expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
  expect(server).toHaveBeenCalledWith(
    "https://other.example.test/status",
    expect.anything(),
  );
  await fireEvent.press(screen.getByText("Save connection"));
  await waitFor(() =>
    expect(SecureStore.setItemAsync).toHaveBeenCalledWith(
      "stride-coach.connection",
      JSON.stringify({
        ...connection,
        serverUrl: "https://other.example.test",
      }),
      expect.anything(),
    ),
  );
  await fireEvent.press(screen.getByText("Forget connection"));
  await waitFor(() => expect(SecureStore.deleteItemAsync).toHaveBeenCalled());
});
test("secure storage failure remains visible and does not claim a save", async () => {
  jest
    .mocked(SecureStore.setItemAsync)
    .mockRejectedValueOnce(new Error("locked"));
  await mount(<SettingsScreen />);
  await waitFor(() =>
    expect(screen.getByLabelText("Server URL").props.value).toBe(
      connection.serverUrl,
    ),
  );
  await fireEvent.press(screen.getByText("Save connection"));
  expect(
    await screen.findByText(
      "Could not update secure settings. Please try again.",
    ),
  ).toBeTruthy();
  expect(screen.queryByText("Connection saved securely.")).toBeNull();
});
test("goal validates dates, reviews setup, and sends the confirmed request", async () => {
  await mount(<GoalScreen />);
  await fireEvent.press(await screen.findByText("Review goal"));
  expect(await screen.findByText(/Use valid YYYY-MM-DD dates/)).toBeTruthy();
  await fireEvent.changeText(
    screen.getByLabelText("Start Monday (YYYY-MM-DD)"),
    "2026-10-05",
  );
  await fireEvent.changeText(
    screen.getByLabelText("Race or completion date (YYYY-MM-DD)"),
    "2026-12-06",
  );
  await fireEvent.press(screen.getByText("Review goal"));
  expect(bodies("/goal")).toEqual([]);
  await fireEvent.press(screen.getByText("Confirm new plan"));
  expect(await screen.findByText("Plan created")).toBeTruthy();
  expect(bodies("/goal")[0].setup).toEqual({
    goal: "5k",
    start: "2026-10-05",
    race_date: "2026-12-06",
    days_per_week: 3,
    long_run_day: 6,
    athlete: { resting_hr: 60, max_hr: 190 },
  });
});

test("corrupt saved settings lead to setup without making requests", async () => {
  jest.mocked(SecureStore.getItemAsync).mockResolvedValueOnce("{broken");
  await mount(<TodayScreen />);
  expect(await screen.findByText("Connect your coach")).toBeTruthy();
  expect(screen.getByText(/Could not read saved settings/)).toBeTruthy();
  expect(server).not.toHaveBeenCalled();
});

test("empty preview cannot issue a live request", async () => {
  server = mockServer({ "/remove": [] });
  await mount(<ActionsScreen />);
  await fireEvent.press(await screen.findByText("Preview Garmin removal"));
  await screen.findByText("No workouts to change.");
  expect(
    screen.getByRole("button", { name: "Confirm live Garmin removal" }),
  ).toBeDisabled();
  await fireEvent.press(screen.getByText("Confirm live Garmin removal"));
  expect(bodies("/remove")).toEqual([{ dry_run: true, apply: false }]);
});

test("switching servers clears the old action preview", async () => {
  await mount(
    <>
      <ActionsRoute />
      <SettingsScreen />
    </>,
  );
  await fireEvent.press(await screen.findByText("Preview Garmin push"));
  await screen.findByText("Confirm live Garmin push");
  await fireEvent.changeText(
    screen.getByLabelText("Server URL"),
    "https://second.example.test",
  );
  await fireEvent.press(screen.getByText("Save connection"));
  await waitFor(() =>
    expect(screen.queryByText("Confirm live Garmin push")).toBeNull(),
  );
  expect(bodies("/push")).toEqual([{ dry_run: true, apply: false }]);
});
