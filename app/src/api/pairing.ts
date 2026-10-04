import { ApiError, Connection, normalizeConnection } from "./client";
import type { components } from "./schema";

export type Pairing = { serverUrl: string; code: string };

export function normalizePairing(server: string, code: string): Pairing {
  const serverUrl = normalizeConnection({
    serverUrl: server,
    token: "pairing",
  }).serverUrl;
  const normalized = code.trim().toUpperCase();
  if (!/^[A-F0-9]{24}$/.test(normalized))
    throw new ApiError(
      "Enter the 24-character pairing code shown on your computer.",
    );
  return { serverUrl, code: normalized };
}

export function parsePairingLink(link: string): Pairing {
  try {
    const url = new URL(link);
    if (
      url.protocol !== "stridecoach:" ||
      url.hostname !== "pair" ||
      (url.pathname !== "" && url.pathname !== "/") ||
      url.username ||
      url.password ||
      url.port ||
      url.hash ||
      url.searchParams.getAll("server").length !== 1 ||
      url.searchParams.getAll("code").length !== 1 ||
      [...url.searchParams.keys()].some(
        (key) => !["server", "code"].includes(key),
      )
    )
      throw new Error();
    return normalizePairing(
      url.searchParams.get("server")!,
      url.searchParams.get("code")!,
    );
  } catch {
    throw new ApiError(
      "This is not a valid Stride Coach pairing QR code. Generate a new code on your computer.",
    );
  }
}

export async function exchangePairing(
  pairing: Pairing,
  fetcher: typeof fetch = fetch,
): Promise<Connection> {
  const { serverUrl, code } = normalizePairing(pairing.serverUrl, pairing.code);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetcher(`${serverUrl}/pairing/exchange`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ code }),
      signal: controller.signal,
      redirect: "error",
    });
    if (response.status === 429)
      throw new ApiError(
        "Too many pairing attempts. Wait one minute before trying again.",
        429,
      );
    if (response.status === 400 || response.status === 422)
      throw new ApiError(
        "This pairing code is invalid, expired, or already used. Generate a new code on your computer.",
        response.status,
      );
    if (!response.ok)
      throw new ApiError(
        "Pairing is unavailable. Check your server and try again.",
        response.status,
      );
    const result: components["schemas"]["PairedToken"] = await response.json();
    if (
      typeof result.token !== "string" ||
      result.token.length < 32 ||
      /\s/.test(result.token)
    )
      throw new ApiError("The server returned an invalid pairing response.");
    return { serverUrl, token: result.token };
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      "Cannot complete pairing. Check your connection. If the code was used, generate a new one.",
    );
  } finally {
    clearTimeout(timer);
  }
}
