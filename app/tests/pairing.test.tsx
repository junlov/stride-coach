import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react-native";
import { Linking, Text } from "react-native";
import * as SecureStore from "expo-secure-store";
import { CameraView, useCameraPermissions } from "expo-camera";
import { parsePairingLink, exchangePairing } from "../src/api/pairing";
import { PairConnection } from "../src/components/pair-connection";
import { ConnectionProvider, useConnection } from "../src/state/connection";
import { ServerConnection } from "../src/components/server-connection";
import { FirstRunGate } from "../src/screens/onboarding";
import { redirectSystemPath } from "../src/app/+native-intent";
import { mockServer, response } from "./fixtures";

jest.mock("expo-camera", () => ({
  CameraView: jest.fn(() => null),
  useCameraPermissions: jest.fn(),
}));
const code = "A123456789ABCDEF01234567";
const serverUrl = "https://coach.example.test";
const token = "synthetic-pairing-token-at-least-32-characters";
const link = `stridecoach://pair?server=${encodeURIComponent(serverUrl)}&code=${code}`;
const press = async (label: string) =>
  fireEvent.press(await screen.findByText(label));

beforeEach(() => {
  jest.clearAllMocks();
  jest.mocked(SecureStore.getItemAsync).mockResolvedValue(null);
  jest.mocked(SecureStore.setItemAsync).mockResolvedValue();
  jest.spyOn(Linking, "getInitialURL").mockResolvedValue(null);
  jest.mocked(useCameraPermissions).mockReturnValue([
    {
      granted: true,
      canAskAgain: true,
      expires: "never",
      status: "granted",
    } as never,
    jest.fn(),
    jest.fn(),
  ]);
  mockServer({ "/pairing/exchange": { token } });
});
afterEach(() => jest.restoreAllMocks());

test("parses only a pairing link with one safe server and code", () => {
  expect(parsePairingLink(link)).toEqual({ serverUrl, code });
  expect(parsePairingLink(link.toLowerCase())).toEqual({ serverUrl, code });
  for (const invalid of [
    "not a url",
    link.replace("stridecoach:", "https:"),
    link.replace("pair?", "other?"),
    link + "&code=" + code,
    link + "&token=secret",
    link + "#secret",
    link.replace(code, "invalid"),
    link.replace(
      encodeURIComponent(serverUrl),
      encodeURIComponent("http://public.test"),
    ),
    link.replace(
      encodeURIComponent(serverUrl),
      encodeURIComponent("https://user:password@host.test"),
    ),
  ])
    expect(() => parsePairingLink(invalid)).toThrow("not a valid Stride Coach");
  expect(redirectSystemPath({ path: link, initial: true })).toBe("/settings");
  expect(redirectSystemPath({ path: "/goal", initial: false })).toBe("/goal");
});

test.each([400, 422, 429, 503])(
  "rejects failed exchange %s without echoing server data",
  async (status) => {
    const fetcher = jest
      .fn()
      .mockResolvedValue(response({ detail: `${code} ${token}` }, status));
    await expect(
      exchangePairing({ serverUrl, code }, fetcher),
    ).rejects.toMatchObject({ status });
    try {
      await exchangePairing({ serverUrl, code }, fetcher);
    } catch (e) {
      expect(String(e)).not.toContain(token);
      expect(String(e)).not.toContain(code);
    }
  },
);

test("exchange uses a POST body with no old token and rejects redirects", async () => {
  const fetcher = jest.fn().mockResolvedValue(response({ token }));
  expect(await exchangePairing({ serverUrl, code }, fetcher)).toEqual({
    serverUrl,
    token,
  });
  expect(fetcher).toHaveBeenCalledWith(
    `${serverUrl}/pairing/exchange`,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ code }),
      redirect: "error",
    }),
  );
  expect(fetcher.mock.calls[0][1].headers.Authorization).toBeUndefined();
  fetcher.mockResolvedValue(response({ token: "bad" }));
  await expect(exchangePairing({ serverUrl, code }, fetcher)).rejects.toThrow(
    "invalid pairing response",
  );
  fetcher.mockRejectedValue(new Error(token));
  await expect(exchangePairing({ serverUrl, code }, fetcher)).rejects.toThrow(
    "Cannot complete pairing",
  );
});

test("scan confirms the host then stores through the existing SecureStore path", async () => {
  const onSaved = jest.fn();
  await render(
    <ConnectionProvider>
      <PairConnection onSaved={onSaved} />
    </ConnectionProvider>,
  );
  await press("Scan to connect");
  const camera = jest.mocked(CameraView).mock.calls.at(-1)![0];
  await act(async () => {
    camera.onBarcodeScanned!({ data: link } as never);
    camera.onBarcodeScanned!({ data: link } as never);
  });
  expect(screen.getByLabelText("Pairing server URL").props.value).toBe(
    serverUrl,
  );
  expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
  await press("Connect to server");
  await waitFor(() =>
    expect(onSaved).toHaveBeenCalledWith(true, { serverUrl, token }),
  );
  expect(SecureStore.setItemAsync).toHaveBeenCalledWith(
    "stride-coach.connection",
    JSON.stringify({ serverUrl, token }),
    { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY },
  );
  const requests = jest
    .mocked(fetch)
    .mock.calls.filter(([url]) => String(url).endsWith("/pairing/exchange"));
  expect(requests).toHaveLength(1);
});

test.each(["expired", "used", "unknown"])(
  "%s code is rejected without changing secure storage",
  async () => {
    jest
      .mocked(fetch)
      .mockResolvedValue(
        response({ detail: "Pairing code is invalid or expired." }, 400),
      );
    await render(
      <ConnectionProvider>
        <PairConnection link={link} />
      </ConnectionProvider>,
    );
    await press("Connect to server");
    await screen.findByText(/invalid, expired, or already used/);
    expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
  },
);

test("failed secure save retries the received credential without reusing the code", async () => {
  jest
    .mocked(SecureStore.setItemAsync)
    .mockRejectedValueOnce(new Error("unavailable"));
  await render(
    <ConnectionProvider>
      <PairConnection link={link} />
    </ConnectionProvider>,
  );
  await press("Connect to server");
  await screen.findByText(/Could not save secure settings/);
  await press("Connect to server");
  await screen.findByText("Connection saved securely.");
  expect(
    jest
      .mocked(fetch)
      .mock.calls.filter(([url]) => String(url).endsWith("/pairing/exchange")),
  ).toHaveLength(1);
});

test("denied camera leaves code entry and close available", async () => {
  jest
    .mocked(useCameraPermissions)
    .mockReturnValue([
      { granted: false, canAskAgain: false } as never,
      jest.fn(),
      jest.fn(),
    ]);
  await render(
    <ConnectionProvider>
      <PairConnection />
    </ConnectionProvider>,
  );
  await press("Scan to connect");
  await screen.findByText("Open phone settings");
  await press("Close scanner");
  await press("Enter pairing code");
  expect(screen.getByLabelText("Pairing code")).toBeTruthy();
});

test("cold deep link waits for hydration and continues onboarding after pairing", async () => {
  jest.mocked(Linking.getInitialURL).mockResolvedValue(link);
  await render(
    <ConnectionProvider>
      <FirstRunGate>
        <Text>Today</Text>
      </FirstRunGate>
    </ConnectionProvider>,
  );
  await press("Connect to server");
  await screen.findByText("Bring your runs together.");
  await press("Skip Garmin for now");
  await press("Go to Today");
  await screen.findByText("Today");
});

test("warm deep link lets an existing connection be replaced or cancelled", async () => {
  jest
    .mocked(SecureStore.getItemAsync)
    .mockResolvedValue(JSON.stringify({ serverUrl, token }));
  const listener = jest.spyOn(Linking, "addEventListener");
  await render(
    <ConnectionProvider>
      <FirstRunGate>
        <Text>Today</Text>
      </FirstRunGate>
    </ConnectionProvider>,
  );
  await screen.findByText("Today");
  const handler = listener.mock.calls.find(([event]) => event === "url")![1];
  await act(async () => handler({ url: link }));
  await screen.findByText("Connect to server");
  await press("Cancel pairing");
  await screen.findByText("Today");
  expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
  await act(async () => handler({ url: link }));
  await press("Connect to server");
  await screen.findByText("Today");
  expect(SecureStore.setItemAsync).toHaveBeenCalledTimes(1);
});

test("plain code entry in connection settings updates the manual fallback fields", async () => {
  jest
    .mocked(SecureStore.getItemAsync)
    .mockResolvedValue(
      JSON.stringify({
        serverUrl: "https://old.example.test",
        token: "old-synthetic-token",
      }),
    );
  await render(
    <ConnectionProvider>
      <FirstRunGate>
        <ServerConnection />
      </FirstRunGate>
    </ConnectionProvider>,
  );
  await press("Enter pairing code");
  await fireEvent.changeText(
    screen.getByLabelText("Pairing server URL"),
    serverUrl,
  );
  await fireEvent.changeText(screen.getByLabelText("Pairing code"), code);
  await press("Connect to server");
  await screen.findByText("Connection saved securely.");
  expect(screen.getByLabelText("Server URL").props.value).toBe(serverUrl);
  expect(screen.getByLabelText("Bearer token").props.value).toBe(token);
});

function ForgetConnection() {
  const { clear } = useConnection();
  return <Text onPress={() => void clear()}>Forget connection</Text>;
}

test("forgetting a deep-linked connection restarts at the server step", async () => {
  jest.mocked(Linking.getInitialURL).mockResolvedValue(link);
  await render(
    <ConnectionProvider>
      <FirstRunGate>
        <ForgetConnection />
      </FirstRunGate>
    </ConnectionProvider>,
  );
  await press("Connect to server");
  await press("Skip Garmin for now");
  await press("Go to Today");
  await press("Forget connection");
  await screen.findByText("Your running. Your server.");
  expect(screen.getByLabelText("Server URL")).toBeTruthy();
});

test("leaving pairing during exchange cannot replace the saved connection", async () => {
  let complete!: (value: Response) => void;
  jest.mocked(fetch).mockImplementation(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  );
  const view = await render(
    <ConnectionProvider>
      <PairConnection link={link} />
    </ConnectionProvider>,
  );
  await press("Connect to server");
  await view.unmount();
  await act(async () => complete(response({ token })));
  expect(SecureStore.setItemAsync).not.toHaveBeenCalled();
});
