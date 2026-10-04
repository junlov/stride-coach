import { useCallback, useState } from "react";
import { AppState } from "react-native";
import { useFocusEffect } from "expo-router";
import { Client } from "../api/client";
import { useConnection } from "./connection";
export function useQuery<T>(
  load: (client: Client) => Promise<T>,
  refreshOnDayChange = false,
) {
  const { client, revision } = useConnection();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(0);
  useFocusEffect(
    useCallback(() => {
      // Re-run the focused query when a write or an explicit retry changes these counters.
      void revision;
      void retry;
      let active = true;
      setData(null);
      setError(null);
      if (!client) {
        setLoading(false);
        return;
      }
      const subscription = AppState.addEventListener("change", (state) => {
        if (state === "active") setRetry((n) => n + 1);
      });
      let midnightTimer: ReturnType<typeof setTimeout> | undefined;
      if (refreshOnDayChange) {
        const now = new Date();
        const midnight = new Date(now);
        midnight.setHours(24, 0, 0, 0);
        midnightTimer = setTimeout(
          () => setRetry((n) => n + 1),
          midnight.getTime() - now.getTime(),
        );
      }
      setLoading(true);
      load(client)
        .then((result) => {
          if (active) setData(result);
        })
        .catch((e: Error) => {
          if (active) setError(e.message);
        })
        .finally(() => {
          if (active) setLoading(false);
        });
      return () => {
        active = false;
        subscription.remove();
        clearTimeout(midnightTimer);
      };
    }, [client, revision, retry, load, refreshOnDayChange]),
  );
  return { data, error, loading, retry: () => setRetry((n) => n + 1) };
}
