import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react-native";
import * as SecureStore from "expo-secure-store";
import { ConnectionProvider } from "../src/state/connection";
import TodayScreen from "../src/screens/today";
import ActionsScreen from "../src/screens/actions";
import { connection, mockServer, response, workout } from "./fixtures";
import { Schema } from "../src/api/client";

const recoveryWorkout: Schema<"Workout"> = {
  id: workout.id,
  day: "2026-10-06",
  week: workout.week,
  phase: workout.phase,
  kind: "tempo",
  steps: workout.steps,
  cutback: workout.cutback,
};
const proposal: Schema<"DailyProposal"> = {
  day: "2026-10-05",
  readiness: {
    day: "2026-10-05",
    fetched_at: "2026-10-05T06:00:00Z",
    training_readiness: 20,
    sleep_score: 40,
    hrv_status: null,
  },
  before: recoveryWorkout,
  after: { ...recoveryWorkout, kind: "easy" },
  reasons: ["Sleep score is 40/100 (below 50)."],
  proposal_fingerprint: "reviewed-daily-change",
  garmin_update_required: true,
};
let server: ReturnType<typeof mockServer>;
beforeEach(() => {
  jest.clearAllMocks();
  jest
    .mocked(SecureStore.getItemAsync)
    .mockResolvedValue(JSON.stringify(connection));
  server = mockServer({
    "/adjustments/daily": proposal,
    "/adapt/daily": { ...proposal, applied: true },
  });
});
const mount = (child = <ActionsScreen />) =>
  render(<ConnectionProvider>{child}</ConnectionProvider>);
const changes = () =>
  server.mock.calls.filter(([url]) => String(url).endsWith("/adapt/daily"));

test("Today explains recovery and proposes review without applying", async () => {
  await mount(<TodayScreen />);
  expect(await screen.findByText("Training Readiness: 20")).toBeTruthy();
  expect(screen.getByText("Sleep score: 40")).toBeTruthy();
  expect(screen.getByText("HRV: unavailable")).toBeTruthy();
  expect(screen.getByText(proposal.reasons[0])).toBeTruthy();
  expect(screen.getByText("Review tomorrow's change")).toBeTruthy();
  expect(changes()).toHaveLength(0);
});

test("daily change requires review and explicit confirmation, with separate Garmin push", async () => {
  await mount();
  await fireEvent.press(await screen.findByText("Preview tomorrow's change"));
  expect(await screen.findByText("Currently planned")).toBeTruthy();
  expect(screen.getByText("Proposed workout")).toBeTruthy();
  expect(screen.getByText("2026-10-06 · tempo")).toBeTruthy();
  expect(screen.getByText("2026-10-06 · easy")).toBeTruthy();
  expect(changes()).toHaveLength(0);
  await fireEvent.press(screen.getByText("Confirm tomorrow’s change"));
  await waitFor(() => expect(changes()).toHaveLength(1));
  const options = (changes()[0] as unknown as [string, RequestInit])[1];
  expect(JSON.parse(options.body as string)).toEqual({
    apply: true,
    proposal_fingerprint: proposal.proposal_fingerprint,
  });
  expect(await screen.findByText(/Tomorrow's change applied/)).toBeTruthy();
  expect(server.mock.calls.some(([url]) => String(url).endsWith("/push"))).toBe(
    false,
  );
  expect(screen.queryByText("Confirm tomorrow’s change")).toBeNull();
});

test("missing recovery gives no confirmable change and cancellation makes no write", async () => {
  server = mockServer({
    "/adjustments/daily": {
      day: "2026-10-05",
      readiness: null,
      reasons: ["No recovery data for today."],
    },
  });
  await mount();
  await fireEvent.press(await screen.findByText("Preview tomorrow's change"));
  expect(await screen.findByText("No recovery data for today.")).toBeTruthy();
  expect(screen.getByText("Confirm tomorrow’s change")).toBeDisabled();
  await fireEvent.press(screen.getByText("Cancel preview"));
  expect(changes()).toHaveLength(0);
});

test("stale confirmation shows the server reason and permits a fresh preview", async () => {
  await mount();
  await fireEvent.press(await screen.findByText("Preview tomorrow's change"));
  await screen.findByText("Confirm tomorrow’s change");
  server.mockResolvedValueOnce(
    response({ detail: "Daily preview is stale. Review again." }, 400),
  );
  await fireEvent.press(screen.getByText("Confirm tomorrow’s change"));
  expect(
    await screen.findByText("Daily preview is stale. Review again."),
  ).toBeTruthy();
  expect(screen.queryByText("Confirm tomorrow’s change")).toBeNull();
  await fireEvent.press(screen.getByText("Preview tomorrow's change"));
  expect(await screen.findByText("Confirm tomorrow’s change")).toBeEnabled();
});
