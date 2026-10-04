import React from "react";
import { fireEvent, render, screen } from "@testing-library/react-native";
import { Text } from "react-native";
import * as SecureStore from "expo-secure-store";
import { ExpoRoot } from "expo-router";
import { getMockContext } from "expo-router/build/testing-library/mock-config";
import RootLayout from "../src/app/_layout";
import { connection, mockServer } from "./fixtures";

jest.unmock("expo-router");

// Exercise the real navigator: first-run content is mounted before the tabs exist.
test("first run from a Settings deep link finishes on Today", async () => {
  jest.mocked(SecureStore.getItemAsync).mockResolvedValue(null);
  jest.mocked(SecureStore.setItemAsync).mockResolvedValue();
  mockServer();
  const context = getMockContext({
    _layout: RootLayout,
    index: () => <Text>Today route</Text>,
    settings: () => <Text>Settings route</Text>,
    goal: () => <Text>Goal route</Text>,
    plan: () => null,
    insights: () => null,
    actions: () => null,
  });
  await render(
    <ExpoRoot
      context={context}
      location={new URL("http://localhost/settings")}
    />,
  );
  await fireEvent.changeText(
    await screen.findByLabelText("Server URL"),
    connection.serverUrl,
  );
  await fireEvent.changeText(
    screen.getByLabelText("Bearer token"),
    connection.token,
  );
  await fireEvent.press(screen.getByText("Test connection"));
  await screen.findByText("Your server is reachable.");
  await fireEvent.press(screen.getByText("Save connection"));
  await fireEvent.press(await screen.findByText("Skip Garmin for now"));
  await fireEvent.press(await screen.findByText("Go to Today"));
  await screen.findByText("Today route");
});
