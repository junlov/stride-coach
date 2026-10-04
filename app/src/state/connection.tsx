import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { AppState } from "react-native";
import * as SecureStore from "expo-secure-store";
import { Connection, createClient, normalizeConnection } from "../api/client";
const KEY = "stride-coach.connection";
type State = {
  connection: Connection | null;
  client: ReturnType<typeof createClient> | null;
  loading: boolean;
  error: string | null;
  revision: number;
  connectionVersion: number;
  onboarding: boolean;
  finishOnboarding: () => void;
  refresh: () => void;
  save: (value: Connection) => Promise<void>;
  clear: () => Promise<void>;
};
const Context = createContext<State | null>(null);
export function ConnectionProvider({ children }: React.PropsWithChildren) {
  const [connection, setConnection] = useState<Connection | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [connectionVersion, setConnectionVersion] = useState(0);
  const [onboarding, setOnboarding] = useState(false);
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const raw = await SecureStore.getItemAsync(KEY);
        const saved = raw ? normalizeConnection(JSON.parse(raw)) : null;
        if (active) {
          setConnection(saved);
          setOnboarding(!saved);
        }
      } catch {
        if (active) setOnboarding(true);
        if (active)
          setError(
            "Could not read saved settings. Enter and save your connection again.",
          );
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);
  const client = useMemo(
    () => (connection ? createClient(connection) : null),
    [connection],
  );
  useEffect(() => {
    if (!client) return;
    let active = true;
    let pending = false;
    async function sync() {
      if (pending || !client) return;
      pending = true;
      try {
        const result = await client.syncOnOpen();
        if (active && !result.skipped) setRevision((n) => n + 1);
      } catch {
        // The read screens retain their retry UI; sync errors are persisted by the server.
      } finally {
        pending = false;
      }
    }
    void sync();
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") void sync();
    });
    return () => {
      active = false;
      subscription.remove();
    };
  }, [client]);
  const value: State = {
    connection,
    client,
    loading,
    error,
    revision,
    connectionVersion,
    onboarding,
    finishOnboarding: () => setOnboarding(false),
    refresh: () => setRevision((n) => n + 1),
    save: async (input) => {
      const normalized = normalizeConnection(input);
      await SecureStore.setItemAsync(KEY, JSON.stringify(normalized), {
        keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
      });
      setConnection(normalized);
      setConnectionVersion((n) => n + 1);
      setError(null);
      setRevision((n) => n + 1);
    },
    clear: async () => {
      await SecureStore.deleteItemAsync(KEY);
      setConnection(null);
      setOnboarding(true);
      setConnectionVersion((n) => n + 1);
      setError(null);
      setRevision((n) => n + 1);
    },
  };
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useConnection() {
  const value = useContext(Context);
  if (!value) throw new Error("ConnectionProvider is required");
  return value;
}
