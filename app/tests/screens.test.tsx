import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react-native";
import { AppState } from "react-native";
import { localDay } from "../src/dates";
import * as SecureStore from "expo-secure-store";
import { ConnectionProvider } from "../src/state/connection";
import ActionsScreen from "../src/screens/actions";
import ActionsRoute from "../src/app/actions";
import SettingsScreen from "../src/screens/settings";
import TodayScreen from "../src/screens/today";
import PlanScreen from "../src/screens/plan";
import InsightsScreen from "../src/screens/insights";
import { HistoryImport } from "../src/components/history-import";
import GoalScreen from "../src/screens/goal";
import { connection, mockServer, plan, response } from "./fixtures";

jest.mock("../src/dates", () => ({
  ...jest.requireActual("../src/dates"),
  localDay: jest.fn(() => "2026-10-05"),
}));
let server: ReturnType<typeof mockServer>;
beforeEach(() => {
  jest.clearAllMocks();
  jest.mocked(localDay).mockReturnValue("2026-10-05");
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
  const original = server.getMockImplementation()!;
  let failed = false;
  server.mockImplementation(async (input) => {
    if (new URL(String(input)).pathname === "/status" && !failed) {
      failed = true;
      throw new Error("offline");
    }
    return original(input);
  });
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
    expect(bodies("/adapt")).toEqual([
      { week: 2, apply: true, proposal_fingerprint: "reviewed-proposal" },
    ]),
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
  await fireEvent.press(await screen.findByText("Manage connection"));
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
  await fireEvent.press(screen.getByText("Forget server connection"));
  await waitFor(() => expect(SecureStore.deleteItemAsync).toHaveBeenCalled());
});
test("secure storage failure remains visible and does not claim a save", async () => {
  jest
    .mocked(SecureStore.setItemAsync)
    .mockRejectedValueOnce(new Error("locked"));
  await mount(<SettingsScreen />);
  await fireEvent.press(await screen.findByText("Manage connection"));
  await waitFor(() =>
    expect(screen.getByLabelText("Server URL").props.value).toBe(
      connection.serverUrl,
    ),
  );
  await fireEvent.press(screen.getByText("Test connection"));
  await screen.findByText("Your server is reachable.");
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
  await fireEvent.press(await screen.findByText("Manage connection"));
  await fireEvent.changeText(
    screen.getByLabelText("Server URL"),
    "https://second.example.test",
  );
  await fireEvent.press(screen.getByText("Test connection"));
  await screen.findByText("Your server is reachable.");
  await fireEvent.press(screen.getByText("Save connection"));
  await waitFor(() =>
    expect(screen.queryByText("Confirm live Garmin push")).toBeNull(),
  );
  expect(bodies("/push")).toEqual([{ dry_run: true, apply: false }]);
});

test.each(["2026-11-30", "2026-12-01", "2026-12-02"])(
  "today uses the completion date for an empty week on %s",
  async (today) => {
    jest.mocked(localDay).mockReturnValue(today);
    server = mockServer({
      "/plan": { ...plan, setup: { ...plan.setup, race_date: "2026-12-01" } },
    });
    await mount(<TodayScreen />);
    expect(
      await screen.findByText(
        today > "2026-12-01"
          ? "Your plan has ended. Review your progress or set a new goal."
          : "No workouts scheduled this week.",
      ),
    ).toBeTruthy();
    expect(
      server.mock.calls.some(([url]) => String(url).includes("/weeks/")),
    ).toBe(false);
  },
);

test("today refreshes when the app resumes after the date changes", async () => {
  const listener = jest.mocked(AppState.addEventListener);
  await mount(<TodayScreen />);
  await screen.findByText("Your workout is ready below.");
  jest.mocked(localDay).mockReturnValue("2026-10-06");
  const listeners = listener.mock.calls.map((call) => call[1]);
  await act(async () => {
    listeners.forEach((onChange) => onChange("background"));
    listeners.forEach((onChange) => onChange("active"));
  });
  expect(
    await screen.findByText("Rest day. Make room for recovery."),
  ).toBeTruthy();
  expect(screen.getByText("2026-10-06 · 5k")).toBeTruthy();
});

test("today refreshes at midnight while the app stays open", async () => {
  jest.useFakeTimers({ now: new Date(2026, 9, 5, 23, 59, 59) });
  try {
    await mount(<TodayScreen />);
    await screen.findByText("Your workout is ready below.");
    jest.mocked(localDay).mockReturnValue("2026-10-06");
    await act(async () => {
      await jest.advanceTimersByTimeAsync(1000);
    });
    expect(
      await screen.findByText("Rest day. Make room for recovery."),
    ).toBeTruthy();
    expect(screen.getByText("2026-10-06 · 5k")).toBeTruthy();
    await screen.unmount();
    const requests = server.mock.calls.length;
    await act(async () => {
      await jest.advanceTimersByTimeAsync(86400000);
    });
    expect(server.mock.calls).toHaveLength(requests);
  } finally {
    jest.useRealTimers();
  }
});

test("Garmin login clears password immediately and completes MFA without persisting it", async () => {
  server = mockServer({
    "/garmin/status": { connected: false },
    "/garmin/login": {
      connected: false,
      mfa_required: true,
      challenge_id: "synthetic-challenge",
    },
    "/garmin/mfa": {
      connected: true,
      display_name: "Synthetic Runner",
      expires_at: null,
    },
    "/garmin/logout": { connected: false },
  });
  await mount(<SettingsScreen />);
  await screen.findByText("Garmin is not connected.");
  await fireEvent.changeText(
    screen.getByLabelText("Garmin email"),
    "runner@example.test",
  );
  await fireEvent.changeText(
    screen.getByLabelText("Garmin password"),
    "synthetic-secret-password",
  );
  let finish!: (value: Response) => void;
  server.mockImplementationOnce(
    () =>
      new Promise<Response>((resolve) => {
        finish = resolve;
      }),
  );
  await fireEvent.press(screen.getByText("Connect Garmin"));
  expect(screen.getByLabelText("Garmin password").props.value).toBe("");
  expect(bodies("/garmin/login")).toEqual([
    { email: "runner@example.test", password: "synthetic-secret-password" },
  ]);
  await act(async () =>
    finish(
      response({
        connected: false,
        mfa_required: true,
        challenge_id: "synthetic-challenge",
      }),
    ),
  );
  await fireEvent.changeText(
    await screen.findByLabelText("Garmin MFA code"),
    "123456",
  );
  await fireEvent.press(screen.getByText("Complete Garmin connection"));
  await screen.findByText("Connected to Garmin as Synthetic Runner.");
  expect(bodies("/garmin/mfa")).toEqual([
    { challenge_id: "synthetic-challenge", code: "123456" },
  ]);
  expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
  await fireEvent.press(screen.getByText("Disconnect Garmin"));
  await fireEvent.press(screen.getByText("Confirm disconnect"));
  await screen.findByText("Garmin is not connected.");
  expect(bodies("/garmin/logout")).toEqual([{}]);
});

test("Garmin wrong password is not echoed and login never retries automatically", async () => {
  server = mockServer({ "/garmin/status": { connected: false } });
  await mount(<SettingsScreen />);
  await screen.findByText("Garmin is not connected.");
  await fireEvent.changeText(
    screen.getByLabelText("Garmin email"),
    "runner@example.test",
  );
  await fireEvent.changeText(
    screen.getByLabelText("Garmin password"),
    "synthetic-secret-password",
  );
  server.mockResolvedValueOnce(
    response({ detail: "synthetic-secret-password" }, 502),
  );
  await fireEvent.press(screen.getByText("Connect Garmin"));
  await screen.findByText(/Garmin connection failed/);
  expect(screen.getByLabelText("Garmin password").props.value).toBe("");
  expect(screen.queryByText("synthetic-secret-password")).toBeNull();
  expect(bodies("/garmin/login")).toHaveLength(1);
  expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
});

test("Garmin login can connect without MFA", async () => {
  server = mockServer({
    "/garmin/status": { connected: false },
    "/garmin/login": { connected: true, display_name: null, expires_at: null },
  });
  await mount(<SettingsScreen />);
  await screen.findByText("Garmin is not connected.");
  await fireEvent.changeText(
    screen.getByLabelText("Garmin email"),
    "runner@example.test",
  );
  await fireEvent.changeText(
    screen.getByLabelText("Garmin password"),
    "synthetic-password",
  );
  await fireEvent.press(screen.getByText("Connect Garmin"));
  await screen.findByText("Connected to Garmin.");
  expect(screen.queryByLabelText("Garmin MFA code")).toBeNull();
});

test.each(["connected", "disconnected", "renewal failure"])(
  "Garmin background status replaces login result on %s",
  async (outcome) => {
    server = mockServer({
      "/garmin/status": { connected: false },
      "/garmin/login": { connected: true },
    });
    await mount(<SettingsScreen />);
    await screen.findByText("Garmin is not connected.");
    await fireEvent.changeText(
      screen.getByLabelText("Garmin email"),
      "runner@example.test",
    );
    await fireEvent.changeText(
      screen.getByLabelText("Garmin password"),
      "synthetic-password",
    );
    await fireEvent.press(screen.getByText("Connect Garmin"));
    await screen.findByText("Connected to Garmin.");
    const fallback = server.getMockImplementation()!;
    server.mockImplementation(async (input) => {
      if (!String(input).endsWith("/garmin/status")) return fallback(input);
      return outcome === "renewal failure"
        ? response({ detail: "Reconnect Garmin in Settings." }, 502)
        : response({
            connected: outcome === "connected",
            display_name: "Refreshed Runner",
          });
    });
    const listeners = jest
      .mocked(AppState.addEventListener)
      .mock.calls.map(([, listener]) => listener);
    await act(async () => {
      listeners.forEach((onChange) => {
        onChange("background");
        onChange("active");
      });
    });
    await screen.findByText(
      outcome === "renewal failure"
        ? "Reconnect Garmin in Settings."
        : outcome === "connected"
          ? "Connected to Garmin as Refreshed Runner."
          : "Garmin is not connected.",
    );
    expect(screen.queryByText("Connected to Garmin.")).toBeNull();
    if (outcome !== "connected") {
      expect(screen.getByLabelText("Garmin password").props.value).toBe("");
      expect(screen.getByText("Connect Garmin")).toBeTruthy();
    }
    expect(bodies("/garmin/login")).toHaveLength(1);
  },
);

test.each(["sync", "push", "remove"])(
  "disconnected Garmin prompts before %s",
  async (action) => {
    server = mockServer({ "/garmin/status": { connected: false } });
    await mount(<ActionsScreen />);
    if (action === "sync") {
      await fireEvent.press(await screen.findByText("Sync activities"));
    } else {
      await fireEvent.press(
        await screen.findByText(
          `Preview Garmin ${action === "push" ? "push" : "removal"}`,
        ),
      );
      await fireEvent.press(
        await screen.findByText(
          `Confirm live Garmin ${action === "push" ? "push" : "removal"}`,
        ),
      );
    }
    await screen.findByText("Connect Garmin in Settings to use this action.");
    expect(
      bodies(`/${action}`).filter((body) => body.apply || action === "sync"),
    ).toEqual([]);
  },
);

test("opening and resuming requests read-only sync without Garmin write actions", async () => {
  await mount(<TodayScreen />);
  await waitFor(() => expect(bodies("/sync/open")).toEqual([{}]));
  const listeners = jest
    .mocked(AppState.addEventListener)
    .mock.calls.map((call) => call[1]);
  await act(async () => listeners.forEach((listener) => listener("active")));
  await waitFor(() => expect(bodies("/sync/open")).toEqual([{}, {}]));
  for (const path of ["/garmin/login", "/push", "/remove", "/adapt"]) {
    expect(bodies(path)).toEqual([]);
  }
});

test("automatic sync does not overlap while a previous app-open request is pending", async () => {
  const original = server.getMockImplementation()!;
  let finish!: (value: Response) => void;
  server.mockImplementation((input) =>
    String(input).endsWith("/sync/open")
      ? new Promise<Response>((resolve) => {
          finish = resolve;
        })
      : original(input),
  );
  await mount(<TodayScreen />);
  await waitFor(() => expect(bodies("/sync/open")).toHaveLength(1));
  const listeners = jest
    .mocked(AppState.addEventListener)
    .mock.calls.map((call) => call[1]);
  await act(async () => listeners.forEach((listener) => listener("active")));
  expect(bodies("/sync/open")).toHaveLength(1);
  await act(async () => finish(response({ skipped: true })));
});

const historyJob = {
  id: "synthetic-history",
  source: "history",
  started_at: "2026-10-04T06:00:00Z",
  since: "2026-07-12",
  until: "2026-10-04",
  result: "running",
  activity_count: 100,
  history_range: "12-weeks",
  next_page: 100,
};

test.each([
  ["12 weeks", "12-weeks"],
  ["6 months", "6-months"],
  ["Everything", "everything"],
])("history import submits %s and displays progress", async (label, range) => {
  server = mockServer({
    "/sync/history": { ...historyJob, history_range: range },
  });
  await mount(<HistoryImport />);
  await fireEvent.press(await screen.findByText(`Import ${label}`));
  expect(bodies("/sync/history")).toEqual([{ range }]);
  expect(
    await screen.findByText("100 runs imported · Importing..."),
  ).toBeTruthy();
  expect(
    screen.getByRole("button", { name: `Import ${label}` }),
  ).toBeDisabled();
});

test("failed imports resume and poll to completion", async () => {
  jest.useFakeTimers();
  try {
    server = mockServer({
      "/sync/status": {
        history: {
          ...historyJob,
          result: "error",
          error: "Reconnect Garmin, then resume.",
        },
      },
      "/sync/history": historyJob,
    });
    const complete = jest.fn();
    await mount(<HistoryImport onComplete={complete} />);
    await fireEvent.press(await screen.findByText("Resume import"));
    expect(bodies("/sync/history")).toEqual([{ range: "12-weeks" }]);
    const original = server.getMockImplementation()!;
    server.mockImplementation(async (input) =>
      String(input).endsWith("/sync/status")
        ? response({
            history: { ...historyJob, result: "success", activity_count: 101 },
          })
        : original(input),
    );
    await act(async () => {
      await jest.advanceTimersByTimeAsync(2000);
    });
    expect(
      await screen.findByText("101 runs imported · Complete"),
    ).toBeTruthy();
    expect(complete).toHaveBeenCalledTimes(1);
  } finally {
    jest.useRealTimers();
  }
});

test("sync status preserves last success alongside reconnect error", async () => {
  server = mockServer({
    "/sync/status": {
      last_success: {
        ...historyJob,
        result: "success",
        finished_at: "2026-10-04T06:01:00Z",
      },
      latest: {
        ...historyJob,
        result: "error",
        error: "Sync failed. Reconnect Garmin.",
      },
    },
  });
  await mount(<TodayScreen />);
  expect(await screen.findByText(/Last synced/)).toBeTruthy();
  expect(
    await screen.findByText("Sync failed. Reconnect Garmin."),
  ).toBeTruthy();
});

test("progress shows persisted reasons for applied adjustments", async () => {
  server = mockServer({
    "/status": {
      plan_id: plan.id,
      scheduled_workouts: 0,
      sync: null,
      weeks: [],
      adjustments: [
        {
          week: 2,
          before_minutes: 60,
          after_minutes: 45,
          factor: 0.75,
          applied: true,
          reasons: [
            "Less than half of last week's sessions completed: reduce 25%.",
          ],
          inputs: { current_week: { matched_sessions: 0 } },
        },
      ],
    },
  });
  await mount(<InsightsScreen />);
  expect(await screen.findByText("Why week 2 changed")).toBeTruthy();
  expect(
    screen.getByText(
      "Less than half of last week's sessions completed: reduce 25%.",
    ),
  ).toBeTruthy();
});

test("a stale adjustment asks for a new review without applying or retrying", async () => {
  const original = server.getMockImplementation()!;
  server.mockImplementation(async (input) =>
    String(input).endsWith("/adapt")
      ? response(
          {
            detail:
              "The adjustment preview is missing or stale. Preview adjustment again and review the new proposal before confirming.",
          },
          400,
        )
      : original(input),
  );
  await mount(<ActionsScreen />);
  await fireEvent.changeText(
    await screen.findByLabelText("Week (blank pushes all future weeks)"),
    "2",
  );
  await fireEvent.press(screen.getByText("Preview adjustment"));
  await fireEvent.press(await screen.findByText("Confirm adjustment"));
  expect(
    await screen.findByText(/Preview adjustment again and review/),
  ).toBeTruthy();
  expect(screen.queryByText("Confirm adjustment")).toBeNull();
  expect(screen.queryByText("The result is unknown.")).toBeNull();
  expect(bodies("/adapt")).toHaveLength(1);
  await fireEvent.press(screen.getByText("Preview adjustment"));
  expect(await screen.findByText("Confirm adjustment")).toBeTruthy();
  expect(bodies("/adapt")).toHaveLength(1);
});

test("resuming replaces a completed local import with another device's job and polls", async () => {
  jest.useFakeTimers();
  try {
    server = mockServer({
      "/sync/history": {
        ...historyJob,
        result: "success",
        finished_at: "2026-10-04T07:00:00Z",
      },
    });
    await mount(<HistoryImport />);
    await fireEvent.press(await screen.findByText("Import 12 weeks"));
    expect(
      await screen.findByText("100 runs imported · Complete"),
    ).toBeTruthy();
    const original = server.getMockImplementation()!;
    let latest = {
      ...historyJob,
      id: "second-device",
      started_at: "2026-10-05T06:00:00Z",
      activity_count: 0,
    };
    server.mockImplementation(async (input) =>
      String(input).endsWith("/sync/status")
        ? response({ history: latest })
        : original(input),
    );
    const listeners = jest
      .mocked(AppState.addEventListener)
      .mock.calls.map((call) => call[1]);
    await act(async () => listeners.forEach((listener) => listener("active")));
    expect(
      await screen.findByText("0 runs imported · Importing..."),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Import 12 weeks" }),
    ).toBeDisabled();
    latest = { ...latest, result: "success", activity_count: 12 };
    await act(async () => {
      await jest.advanceTimersByTimeAsync(2000);
    });
    expect(await screen.findByText("12 runs imported · Complete")).toBeTruthy();
  } finally {
    jest.useRealTimers();
  }
});
