import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react-native";
import * as SecureStore from "expo-secure-store";
import { ConnectionProvider } from "../src/state/connection";
import {
  GarminCalendar,
  GarminWindowSettings,
} from "../src/components/garmin-calendar";
import { connection, mockServer, response, status } from "./fixtures";

const preview = {
  window_days: 14,
  since: "2026-10-05",
  until: "2026-10-18",
  preview_id: "reviewed-calendar",
  applied: false,
  changes: [
    { action: "create", date: "2026-10-06" },
    { action: "update", date: "2026-10-07" },
    { action: "remove", reason: "Outside the Garmin window" },
  ],
};
let server: ReturnType<typeof mockServer>;
beforeEach(() => {
  jest.clearAllMocks();
  jest
    .mocked(SecureStore.getItemAsync)
    .mockResolvedValue(JSON.stringify(connection));
  server = mockServer({
    "/status": { ...status, garmin_out_of_date: true, garmin_window_days: 14 },
    "/calendar": preview,
  });
});
function bodies(path: string) {
  return (server as jest.Mock).mock.calls
    .filter(([url, init]) => url.endsWith(path) && init.body)
    .map(([, init]) => JSON.parse(init.body));
}
test("calendar offers a combined preview and applies only its explicit confirmation", async () => {
  await render(
    <ConnectionProvider>
      <GarminCalendar />
    </ConnectionProvider>,
  );
  expect(await screen.findByText("Garmin is out of date")).toBeTruthy();
  expect(bodies("/calendar")).toEqual([]);
  await fireEvent.press(screen.getByText("Preview calendar changes"));
  expect(await screen.findByText("Outside the Garmin window")).toBeTruthy();
  expect(screen.getByText("create")).toBeTruthy();
  expect(screen.getByText("update")).toBeTruthy();
  expect(bodies("/calendar")).toEqual([{ apply: false }]);
  await fireEvent.press(screen.getByText("Confirm calendar changes"));
  await waitFor(() =>
    expect(bodies("/calendar")).toEqual([
      { apply: false },
      { apply: true, preview_id: "reviewed-calendar" },
    ]),
  );
});
test("cancel causes no write and failed confirmation requires a new preview", async () => {
  const original = server.getMockImplementation()!;
  server.mockImplementation(async (input, init?: RequestInit) => {
    if (
      String(input).endsWith("/calendar") &&
      JSON.parse(init?.body as string).apply
    )
      return response(
        { detail: "Garmin preview changed. Preview again." },
        400,
      );
    return original(input);
  });
  await render(
    <ConnectionProvider>
      <GarminCalendar />
    </ConnectionProvider>,
  );
  await fireEvent.press(await screen.findByText("Preview calendar changes"));
  await fireEvent.press(await screen.findByText("Cancel calendar preview"));
  expect(screen.queryByText("Confirm calendar changes")).toBeNull();
  expect(bodies("/calendar")).toEqual([{ apply: false }]);
  await fireEvent.press(screen.getByText("Preview calendar changes"));
  await fireEvent.press(await screen.findByText("Confirm calendar changes"));
  expect(
    await screen.findByText("Garmin preview changed. Preview again."),
  ).toBeTruthy();
  expect(screen.queryByText("Confirm calendar changes")).toBeNull();
  await fireEvent.press(screen.getByText("Preview calendar changes"));
  expect(await screen.findByText("Confirm calendar changes")).toBeTruthy();
});
test("window validates bounds, persists a setting and never writes Garmin", async () => {
  await render(
    <ConnectionProvider>
      <GarminWindowSettings />
    </ConnectionProvider>,
  );
  const field = await screen.findByLabelText("Days on Garmin (7 to 28)");
  await fireEvent.changeText(field, "29");
  await fireEvent.press(screen.getByText("Save Garmin window"));
  expect(
    await screen.findByText("Choose a whole number from 7 to 28 days."),
  ).toBeTruthy();
  expect(bodies("/calendar/settings")).toEqual([]);
  await fireEvent.changeText(field, "7");
  await fireEvent.press(screen.getByText("Save Garmin window"));
  expect(
    await screen.findByText(
      "Window saved. Preview calendar changes before updating Garmin.",
    ),
  ).toBeTruthy();
  expect(bodies("/calendar/settings")).toEqual([{ window_days: 7 }]);
  expect(bodies("/calendar")).toEqual([]);
});
