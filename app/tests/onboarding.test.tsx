import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react-native";
import * as Native from "react-native";
import * as SecureStore from "expo-secure-store";
import { ConnectionProvider } from "../src/state/connection";
import { FirstRunGate } from "../src/screens/onboarding";
import SettingsScreen from "../src/screens/settings";
import TodayScreen from "../src/screens/today";
import { palettes } from "../src/theme";
import { connection, mockServer, response, status } from "./fixtures";

jest.mock("../src/dates", () => ({
  ...jest.requireActual("../src/dates"),
  localDay: () => "2026-10-05",
}));

let server: ReturnType<typeof mockServer>;
const press = async (label: string) =>
  fireEvent.press(await screen.findByText(label));
const field = async (label: string, value: string) =>
  fireEvent.changeText(await screen.findByLabelText(label), value);
const calls = (path: string) =>
  server.mock.calls.filter(([url]) => String(url).endsWith(path));
async function mount(child: React.ReactNode) {
  await render(<ConnectionProvider>{child}</ConnectionProvider>);
}
async function enterServer() {
  await field("Server URL", connection.serverUrl);
  await field("Bearer token", connection.token);
  await press("Test connection");
  await screen.findByText("Your server is reachable.");
}
async function login() {
  await screen.findByText("Garmin is not connected.");
  await field("Garmin email", "runner@example.test");
  await field("Garmin password", "synthetic-password");
  await press("Connect Garmin");
}

beforeEach(() => {
  jest.clearAllMocks();
  jest
    .mocked(SecureStore.getItemAsync)
    .mockResolvedValue(JSON.stringify(connection));
  jest.mocked(SecureStore.setItemAsync).mockResolvedValue();
  jest.mocked(SecureStore.deleteItemAsync).mockResolvedValue();
  server = mockServer();
});

describe.each(["light", "dark"] as const)(
  "%s onboarding and settings",
  (theme) => {
    beforeEach(() => {
      jest.spyOn(Native, "useColorScheme").mockReturnValue(theme);
    });
    afterEach(() => jest.restoreAllMocks());

    test.each([false, true])(
      "fresh install to Today, Garmin connected: %s",
      async (connectGarmin) => {
        jest.mocked(SecureStore.getItemAsync).mockResolvedValue(null);
        const transport = mockServer({
          "/garmin/status": { connected: false },
          "/garmin/login": { connected: true },
        });
        let created = false;
        server = jest.fn(async (...args: Parameters<typeof transport>) => {
          const path = new URL(String(args[0])).pathname;
          if (path === "/status" && !created)
            return response(
              { detail: "No plan. Run stride-coach init first." },
              400,
            );
          if (path === "/goal") created = true;
          return transport(...args);
        });
        global.fetch = server as typeof fetch;
        await mount(
          <FirstRunGate>
            <TodayScreen />
          </FirstRunGate>,
        );
        expect(
          await screen.findByText("Your running. Your server."),
        ).toHaveStyle({ color: palettes[theme].text });
        expect(
          screen.getByRole("button", { name: "Save connection" }),
        ).toBeDisabled();
        await enterServer();
        expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
        await press("Save connection");
        if (connectGarmin) {
          await login();
          await screen.findByText("Connected to Garmin.");
          await press("Continue to import");
          await screen.findByText("Import past runs");
          await press("Skip import for now");
        } else await press("Skip Garmin for now");
        expect(screen.queryByText("Import past runs")).toBeNull();
        await press("Goal: 5K ▾");
        await press("Half marathon");
        await press("Days per week: 3 days ▾");
        await press("4 days");
        await press("Long-run day: Sunday ▾");
        await press("Saturday");
        await field("Start Monday (YYYY-MM-DD)", "2026-10-05");
        await field("Race or completion date (YYYY-MM-DD)", "2026-12-06");
        await press("Review goal");
        await screen.findByText("A plan that fits your week.");
        expect(calls("/goal")).toHaveLength(0);
        await press("Confirm new plan");
        await screen.findByText("Plan created");
        await press("Go to Today");
        await screen.findByRole("header", { name: "Make room for easy." });
        expect(calls("/goal")).toHaveLength(1);
        const goalRequest = (server as jest.Mock).mock.calls.find(([url]) =>
          String(url).endsWith("/goal"),
        )[1];
        expect(JSON.parse(goalRequest.body).setup).toMatchObject({
          goal: "half",
          days_per_week: 4,
          long_run_day: 5,
        });
        expect(calls("/garmin/login")).toHaveLength(connectGarmin ? 1 : 0);
        expect(SecureStore.setItemAsync).toHaveBeenCalledWith(
          "stride-coach.connection",
          JSON.stringify(connection),
          { keychainAccessible: "device" },
        );
      },
    );

    test.each(["committed", "status unavailable", "not committed"])(
      "lost goal response recovers only after status confirms a plan: %s",
      async (outcome) => {
        jest.mocked(SecureStore.getItemAsync).mockResolvedValue(null);
        const transport = server.getMockImplementation()!;
        let attempted = false;
        let statusUnavailable = outcome === "status unavailable";
        server.mockImplementation(async (input) => {
          const path = new URL(String(input)).pathname;
          if (path === "/goal") {
            attempted = true;
            throw new Error("Response lost");
          }
          if (path === "/status") {
            if (attempted && statusUnavailable) throw new Error("Offline");
            if (!attempted || outcome === "not committed")
              return response(
                { detail: "No plan. Run stride-coach init first." },
                400,
              );
          }
          return transport(input);
        });
        await mount(
          <FirstRunGate>
            <Native.Text>Today destination</Native.Text>
          </FirstRunGate>,
        );
        await enterServer();
        await press("Save connection");
        await press("Skip Garmin for now");
        await field("Start Monday (YYYY-MM-DD)", "2026-10-05");
        await field("Race or completion date (YYYY-MM-DD)", "2026-12-06");
        await press("Review goal");
        await press("Confirm new plan");
        if (outcome !== "committed") {
          await waitFor(() =>
            expect(
              screen.getByRole("button", { name: "Check plan status" }),
            ).toBeEnabled(),
          );
          expect(screen.queryByText("Go to Today")).toBeNull();
          expect(
            screen.getByLabelText("Start Monday (YYYY-MM-DD)").props.value,
          ).toBe("2026-10-05");
          statusUnavailable = false;
          await press("Check plan status");
        }
        if (outcome === "not committed") {
          await screen.findByText("No plan. Run stride-coach init first.");
          expect(screen.queryByText("Go to Today")).toBeNull();
          await press("Review goal");
          await screen.findByText("Review your goal");
        } else {
          await screen.findByText(
            "Your server confirms an existing plan. Continue to Today.",
          );
          await press("Go to Today");
          await screen.findByText("Today destination");
        }
        expect(calls("/goal")).toHaveLength(1);
      },
    );

    test("existing server plan bypasses creation and a saved install bypasses wizard", async () => {
      jest.mocked(SecureStore.getItemAsync).mockResolvedValue(null);
      await mount(
        <FirstRunGate>
          <Native.Text>Today destination</Native.Text>
        </FirstRunGate>,
      );
      await enterServer();
      await press("Save connection");
      await press("Skip Garmin for now");
      await screen.findByText("Your plan is ready.");
      await press("Go to Today");
      await screen.findByText("Today destination");
      expect(calls("/goal")).toHaveLength(0);
      await screen.unmount();
      jest
        .mocked(SecureStore.getItemAsync)
        .mockResolvedValue(JSON.stringify(connection));
      await mount(
        <FirstRunGate>
          <Native.Text>Today destination</Native.Text>
        </FirstRunGate>,
      );
      await screen.findByText("Today destination");
      expect(screen.queryByText("Your running. Your server.")).toBeNull();
    });

    test("overview, manage, test, changed draft, save, cancel removal, forget outcome", async () => {
      await mount(<SettingsScreen />);
      expect(await screen.findByText("Private by default.")).toHaveStyle({
        color: palettes[theme].text,
      });
      await screen.findByText("Your data");
      await press("Manage connection");
      await press("Test connection");
      await screen.findByText("Your server is reachable.");
      await field("Bearer token", "another-synthetic-token");
      expect(
        screen.getByRole("button", { name: "Save connection" }),
      ).toBeDisabled();
      await press("Test connection");
      await screen.findByText("Your server is reachable.");
      await press("Save connection");
      await screen.findByText("Connection saved securely.");
      await press("Forget connection");
      expect(SecureStore.deleteItemAsync).not.toHaveBeenCalled();
      await press("Keep connection");
      expect(SecureStore.deleteItemAsync).not.toHaveBeenCalled();
      await press("Forget connection");
      await press("Forget server connection");
      await screen.findByText("Saved connection removed.");
      expect(calls("/garmin/logout")).toHaveLength(0);
    });

    test("failed test blocks save and failed forget keeps saved connection", async () => {
      await mount(<SettingsScreen />);
      await press("Manage connection");
      server.mockResolvedValueOnce(response({}, 401));
      await press("Test connection");
      await screen.findByText(/Authentication failed/);
      expect(
        screen.getByRole("button", { name: "Save connection" }),
      ).toBeDisabled();
      jest
        .mocked(SecureStore.deleteItemAsync)
        .mockRejectedValueOnce(new Error("locked"));
      await press("Forget connection");
      await press("Forget server connection");
      await screen.findByText(
        "Could not remove secure settings. Please try again.",
      );
      await press("Keep connection");
      expect(screen.getByLabelText("Server URL").props.value).toBe(
        connection.serverUrl,
      );
    });

    test("Garmin MFA failure consumes challenge, restart signs in explicitly", async () => {
      server = mockServer({
        "/garmin/status": { connected: false },
        "/garmin/login": {
          connected: false,
          mfa_required: true,
          challenge_id: "synthetic-challenge",
        },
      });
      await mount(<SettingsScreen />);
      await login();
      await screen.findByText("One more step.");
      await field("Garmin MFA code", "123456");
      server.mockResolvedValueOnce(response({ detail: "123456 secret" }, 401));
      await press("Complete Garmin connection");
      await screen.findByText("Code not accepted");
      expect(screen.queryByText("123456 secret")).toBeNull();
      expect(screen.queryByLabelText("Garmin MFA code")).toBeNull();
      await press("Restart Garmin sign-in");
      expect(screen.getByLabelText("Garmin password").props.value).toBe("");
      expect(calls("/garmin/mfa")).toHaveLength(1);
      expect(calls("/garmin/login")).toHaveLength(1);
      expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
    });

    test("connected, disconnect cancel, failed disconnect, confirmed outcome and reconnect", async () => {
      server = mockServer({
        "/garmin/logout": { connected: false },
        "/status": {
          ...status,
          sync: { since: "2026-09-07", until: "2026-10-04" },
        },
      });
      await mount(<SettingsScreen />);
      await screen.findByText("Connected through your server.");
      await screen.findByText("Coverage starts: 2026-09-07");
      await screen.findByText("Coverage through: 2026-10-04");
      await press("Disconnect Garmin");
      await press("Keep Garmin connected");
      expect(calls("/garmin/logout")).toHaveLength(0);
      await press("Disconnect Garmin");
      server.mockRejectedValueOnce(new Error("offline"));
      await press("Confirm disconnect");
      await screen.findByText(/Could not disconnect Garmin/);
      await press("Confirm disconnect");
      await screen.findByText(
        "Garmin disconnected. Your plan, stored activities and existing Garmin workouts are unchanged.",
      );
      await press("Reconnect Garmin");
      expect(screen.getByLabelText("Garmin password").props.value).toBe("");
      expect(calls("/garmin/login")).toHaveLength(0);
      expect(calls("/remove")).toHaveLength(0);
    });

    test("activity coverage stays unavailable without a plan and recovers on retry", async () => {
      const transport = server.getMockImplementation()!;
      server.mockImplementation(async (input) => {
        if (new URL(String(input)).pathname === "/status")
          return response(
            { detail: "No plan. Run stride-coach init first." },
            400,
          );
        return transport(input);
      });
      await mount(<SettingsScreen />);
      await screen.findByText(/Activity coverage is unavailable/);
      expect(
        screen.queryByText("No activity sync coverage recorded yet."),
      ).toBeNull();
      expect(screen.getByText("Connected through your server.")).toBeTruthy();

      server.mockImplementation(transport);
      await press("Retry activity coverage");
      await screen.findByText("No activity sync coverage recorded yet.");
      expect(screen.queryByText(/Activity coverage is unavailable/)).toBeNull();
    });

    test("status failure offers explicit reconnect without claiming an expired session", async () => {
      server.mockResolvedValueOnce(
        response({ detail: "Reconnect Garmin in Settings." }, 502),
      );
      await mount(<SettingsScreen />);
      await screen.findByText("Reconnect when you are ready.");
      await press("Reconnect Garmin");
      expect(screen.getByLabelText("Garmin password").props.value).toBe("");
      expect(calls("/garmin/login")).toHaveLength(0);
    });
  },
);

test("saved empty plan provides a goal entry instead of retrying a missing plan", async () => {
  const original = server.getMockImplementation()!;
  server.mockImplementation(async (input) =>
    new URL(String(input)).pathname === "/status"
      ? response({ detail: "No plan. Run stride-coach init first." }, 400)
      : original(input),
  );
  await mount(<TodayScreen />);
  await screen.findByText("Start with a destination.");
  await screen.findByText("Set a running goal");
  expect(screen.queryByText("Retry")).toBeNull();
});

test("storage hydration does not flash setup", async () => {
  let resolve!: (value: string | null) => void;
  jest.mocked(SecureStore.getItemAsync).mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  await mount(
    <FirstRunGate>
      <Native.Text>Today destination</Native.Text>
    </FirstRunGate>,
  );
  expect(screen.queryByText("Your running. Your server.")).toBeNull();
  expect(screen.getByLabelText("Loading settings")).toBeTruthy();
  resolve(JSON.stringify(connection));
  await waitFor(() =>
    expect(screen.getByText("Today destination")).toBeTruthy(),
  );
});

test("wizard imports Garmin history before goal setup", async () => {
  jest.mocked(SecureStore.getItemAsync).mockResolvedValue(null);
  const completed = {
    id: "wizard-import",
    source: "history",
    history_range: "12-weeks",
    started_at: "2026-10-04T06:00:00Z",
    finished_at: "2026-10-04T06:01:00Z",
    since: "2026-07-12",
    until: "2026-10-04",
    activity_count: 12,
    result: "success",
    next_page: 12,
  };
  server = mockServer({ "/sync/history": completed });
  const original = server.getMockImplementation()!;
  server.mockImplementation(async (input) =>
    new URL(String(input)).pathname === "/status"
      ? response({ detail: "No plan. Run stride-coach init first." }, 400)
      : original(input),
  );
  await mount(
    <FirstRunGate>
      <Native.Text>Today destination</Native.Text>
    </FirstRunGate>,
  );
  await enterServer();
  await press("Save connection");
  await press("Continue to import");
  expect(await screen.findByText("Import past runs")).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Continue to goal" }),
  ).toBeDisabled();
  await press("Import 12 weeks");
  await screen.findByText("12 runs imported · Complete");
  await press("Continue to goal");
  await screen.findByLabelText("Start Monday (YYYY-MM-DD)");
  expect(calls("/sync/history")).toHaveLength(1);
  expect(calls("/goal")).toHaveLength(0);
  expect(calls("/push")).toHaveLength(0);
  expect(calls("/adapt")).toHaveLength(0);
});
