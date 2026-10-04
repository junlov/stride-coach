import { createClient, normalizeConnection } from "../src/api/client";
import { connection, mockServer, response, status } from "./fixtures";
import { localDay, validDate, weekForDate } from "../src/dates";

afterEach(() => jest.useRealTimers());
test("normalizes the URL and sends bearer auth without credentials in the URL", async () => {
  const server = mockServer();
  const client = createClient({
    ...connection,
    serverUrl: `${connection.serverUrl}/`,
  });
  await expect(client.status()).resolves.toEqual(status);
  expect(server).toHaveBeenCalledWith(
    `${connection.serverUrl}/status`,
    expect.objectContaining({
      method: "GET",
      headers: expect.objectContaining({
        Authorization: `Bearer ${connection.token}`,
      }),
      redirect: "error",
    }),
  );
});
test("preserves a reverse proxy base path", async () => {
  const fetcher = jest.fn().mockResolvedValue(response(status));
  await createClient(
    { ...connection, serverUrl: `${connection.serverUrl}/coach/` },
    fetcher,
  ).status();
  expect(fetcher.mock.calls[0][0]).toBe(`${connection.serverUrl}/coach/status`);
});
test.each([
  "http://remote.example",
  "https://user:secret@example.com",
  "https://example.com?token=x",
  "https://example.com/#x",
  "file:///tmp/db",
  "invalid",
])("rejects unsafe URL %s", (serverUrl) => {
  expect(() => normalizeConnection({ ...connection, serverUrl })).toThrow();
});
test("allows emulator loopback and rejects blank tokens", () => {
  expect(
    normalizeConnection({ ...connection, serverUrl: "http://10.0.2.2:8000" })
      .serverUrl,
  ).toBe("http://10.0.2.2:8000");
  expect(() => normalizeConnection({ ...connection, token: "" })).toThrow(
    "bearer token",
  );
});
test("401 and offline responses have actionable errors", async () => {
  await expect(
    createClient(
      connection,
      jest.fn().mockResolvedValue(response({}, 401)),
    ).status(),
  ).rejects.toThrow("Authentication failed");
  await expect(
    createClient(
      connection,
      jest.fn().mockRejectedValue(new Error(connection.token)),
    ).status(),
  ).rejects.toThrow("Cannot reach your server");
});
test("handles validation and unreadable responses without leaking the token", async () => {
  await expect(
    createClient(
      connection,
      jest
        .fn()
        .mockResolvedValue(
          response({ detail: [{ msg: "Invalid Monday" }] }, 422),
        ),
    ).status(),
  ).rejects.toThrow("Invalid Monday");
  await expect(
    createClient(
      connection,
      jest.fn().mockResolvedValue(response({ detail: connection.token }, 400)),
    ).status(),
  ).rejects.toThrow("[redacted]");
  await expect(
    createClient(
      connection,
      jest.fn().mockResolvedValue({
        status: 502,
        json: async () => {
          throw new Error("HTML");
        },
      }),
    ).status(),
  ).rejects.toThrow("unreadable response");
});
test("aborts timed out calls and does not automatically retry writes", async () => {
  jest.useFakeTimers();
  const fetcher = jest.fn(
    (_url, init) =>
      new Promise<Response>((_resolve, reject) =>
        init.signal.addEventListener("abort", () =>
          reject(new Error("aborted")),
        ),
      ),
  );
  const pending = createClient(connection, fetcher, 100).push({ apply: true });
  const assertion = expect(pending).rejects.toThrow("too long");
  await jest.advanceTimersByTimeAsync(101);
  await assertion;
  expect(fetcher).toHaveBeenCalledTimes(1);
});
test("serializes preview and apply as separate requests", async () => {
  const server = mockServer();
  const client = createClient(connection);
  await client.push({ week: 2, dry_run: true, apply: false });
  await client.push({ week: 2, dry_run: false, apply: true });
  const calls = (server as jest.Mock).mock.calls;
  expect(JSON.parse(calls[0][1].body)).toEqual({
    week: 2,
    dry_run: true,
    apply: false,
  });
  expect(JSON.parse(calls[1][1].body)).toEqual({
    week: 2,
    dry_run: false,
    apply: true,
  });
});
test("uses calendar days across DST and plan boundaries", () => {
  expect(weekForDate("2026-03-02", "2026-03-09")).toBe(2);
  expect(weekForDate("2026-03-02", "2026-03-01")).toBe(0);
  expect(localDay(new Date(2026, 9, 5, 23))).toBe("2026-10-05");
  expect(validDate("2026-02-30")).toBe(false);
});
