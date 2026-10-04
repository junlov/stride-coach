import { useCallback, useState } from "react";
import { useFocusEffect } from "expo-router";
import { Client } from "../api/client";
import { useConnection } from "./connection";
export function useQuery<T>(load: (client: Client) => Promise<T>) {
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
      };
    }, [client, revision, retry, load]),
  );
  return { data, error, loading, retry: () => setRetry((n) => n + 1) };
}
