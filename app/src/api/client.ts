import type { components, operations } from "./schema";

export type Schema<K extends keyof components["schemas"]> =
  components["schemas"][K];
type Result<K extends keyof operations> =
  operations[K]["responses"][200]["content"]["application/json"];
export type Connection = { serverUrl: string; token: string };
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export function normalizeConnection(connection: Connection): Connection {
  let url: URL;
  try {
    url = new URL(connection.serverUrl.trim());
  } catch {
    throw new ApiError("Enter a valid HTTPS server URL.");
  }
  const local = ["localhost", "127.0.0.1", "[::1]", "10.0.2.2"].includes(
    url.hostname,
  );
  if (url.protocol !== "https:" && !(url.protocol === "http:" && local))
    throw new ApiError(
      "Use HTTPS for your server. HTTP is only allowed on a local emulator or localhost.",
    );
  if (url.username || url.password || url.search || url.hash)
    throw new ApiError(
      "The server URL cannot contain credentials, a query, or a fragment.",
    );
  const token = connection.token.trim();
  if (!token || /\s/.test(token))
    throw new ApiError("Enter the server bearer token without spaces.");
  return { serverUrl: url.toString().replace(/\/+$/, ""), token };
}
export function createClient(
  connection: Connection,
  fetcher: typeof fetch = fetch,
  timeoutMs = 15000,
) {
  const config = normalizeConnection(connection);
  async function request<T>(
    path: string,
    body?: unknown,
    waitMs = timeoutMs,
  ): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), waitMs);
    try {
      const response = await fetcher(`${config.serverUrl}${path}`, {
        method: body === undefined ? "GET" : "POST",
        headers: {
          Authorization: `Bearer ${config.token}`,
          Accept: "application/json",
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
        redirect: "error",
      });
      if (response.status === 401)
        throw new ApiError(
          "Authentication failed. Check your bearer token in Settings.",
          401,
        );
      let data: unknown;
      try {
        data = await response.json();
      } catch {
        throw new ApiError(
          "The server returned an unreadable response. Check the server URL.",
          response.status,
        );
      }
      if (!response.ok) {
        const detail =
          data && typeof data === "object" && "detail" in data
            ? data.detail
            : undefined;
        const message =
          typeof detail === "string"
            ? detail
            : Array.isArray(detail)
              ? detail
                  .map((item) =>
                    typeof item?.msg === "string" ? item.msg : "Invalid field",
                  )
                  .join(". ")
              : `Server request failed (${response.status}).`;
        throw new ApiError(
          message.split(config.token).join("[redacted]"),
          response.status,
        );
      }
      return data as T;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(
        controller.signal.aborted
          ? "The server took too long to respond. Check its status before retrying an action."
          : "Cannot reach your server. Check your connection and server URL. If an action was running, check its status before retrying.",
      );
    } finally {
      clearTimeout(timer);
    }
  }
  return {
    garminStatus: () => request<Result<"garmin_status">>("/garmin/status"),
    garminLogin: (body: Schema<"GarminLogin">) =>
      request<Result<"garmin_login">>("/garmin/login", body, 120000),
    garminMfa: (body: Schema<"GarminMFA">) =>
      request<Result<"garmin_mfa">>("/garmin/mfa", body, 120000),
    garminLogout: () => request<Result<"garmin_logout">>("/garmin/logout", {}),
    syncStatus: () => request<Result<"get_sync_status">>("/sync/status"),
    syncOnOpen: () => request<Result<"sync_on_open">>("/sync/open", {}, 120000),
    importHistory: (range: Schema<"HistoryRequest">["range"]) =>
      request<Result<"import_history">>("/sync/history", { range }),
    status: () => request<Result<"get_status">>("/status"),
    plan: () => request<Result<"get_plan">>("/plan"),
    week: (number: number) => request<Result<"get_week">>(`/weeks/${number}`),
    activity: (id: string) =>
      request<Result<"get_activity">>(`/activities/${encodeURIComponent(id)}`),
    activityStreams: (id: string) =>
      request<Result<"get_activity_streams">>(
        `/activities/${encodeURIComponent(id)}/streams`,
      ),
    load: () => request<Result<"get_load">>("/load"),
    compliance: () => request<Result<"get_compliance">>("/compliance"),
    goal: (body: Schema<"GoalRequest">) =>
      request<Result<"setup_goal">>("/goal", body),
    sync: (body: Schema<"SyncRequest"> = {}) =>
      request<Result<"sync_activities">>("/sync", body, 180000),
    propose: (number: number) =>
      request<Result<"propose_adjustment">>(
        `/adjustments/propose/${number}`,
        {},
      ),
    adapt: (body: Schema<"AdaptRequest">) =>
      request<Result<"adapt_week">>("/adapt", body),
    push: (body: Schema<"PushRequest">) =>
      request<Result<"push_plan">>("/push", body),
    remove: (body: Schema<"RemoveRequest">) =>
      request<Result<"remove_owned_workouts">>("/remove", body),
  };
}
export type Client = ReturnType<typeof createClient>;
