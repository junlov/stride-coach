import { useRef, useState } from "react";
import { ApiError, createClient } from "../api/client";
import { useConnection } from "../state/connection";
import { Button, Card, Copy, ErrorMessage, Field, Heading, Muted } from "./ui";

export function isMissingPlan(error: unknown) {
  return (
    error instanceof ApiError &&
    error.status === 400 &&
    /^No plan\./i.test(error.message)
  );
}

export function ServerConnection({
  onSaved,
}: {
  onSaved?: (hasPlan: boolean) => void;
}) {
  const { connection, save, loading, error: storageError } = useConnection();
  const [url, setUrl] = useState(connection?.serverUrl ?? "");
  const [token, setToken] = useState(connection?.token ?? "");
  const [tested, setTested] = useState<{ hasPlan: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lock = useRef(false);
  function edit(set: (value: string) => void, value: string) {
    set(value);
    setTested(null);
    setSaved(false);
    setError(null);
  }
  async function run(action: "test" | "save") {
    if (lock.current || (action === "save" && !tested)) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      if (action === "test") {
        setTested(null);
        try {
          await createClient({ serverUrl: url, token }).status();
          setTested({ hasPlan: true });
        } catch (e) {
          if (isMissingPlan(e)) setTested({ hasPlan: false });
          else throw e;
        }
      } else {
        await save({ serverUrl: url, token });
        setSaved(true);
        onSaved?.(tested!.hasPlan);
      }
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Could not update secure settings. Please try again.",
      );
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <Card>
      <Field
        label="Server URL"
        value={url}
        onChangeText={(v) => edit(setUrl, v)}
        autoCapitalize="none"
        autoCorrect={false}
        keyboardType="url"
        placeholder="https://coach.example.com"
        editable={!busy && !loading}
      />
      <Field
        label="Bearer token"
        value={token}
        onChangeText={(v) => edit(setToken, v)}
        secureTextEntry
        autoCapitalize="none"
        autoCorrect={false}
        editable={!busy && !loading}
      />
      <Muted>
        The server token authenticates this app. It is separate from your Garmin
        session. Your URL and token stay in this device’s secure storage.
      </Muted>
      {tested && (
        <>
          <Heading>Your server is reachable.</Heading>
          <Copy>
            {tested.hasPlan
              ? "Connected. Authentication and status are working."
              : "Authentication accepted. No active plan yet. Save your connection to set a running goal."}
          </Copy>
          {!saved && (
            <Muted>Ready to save. The connection is not saved yet.</Muted>
          )}
        </>
      )}
      <ErrorMessage message={error ?? storageError} />
      {saved && <Copy>Connection saved securely.</Copy>}
      <Button
        label={busy ? "Working..." : "Test connection"}
        onPress={() => void run("test")}
        disabled={busy || loading}
        variant="secondary"
      />
      <Button
        label="Save connection"
        onPress={() => void run("save")}
        disabled={busy || loading || !tested}
      />
      {!tested && <Muted>Save only after the connection test passes.</Muted>}
    </Card>
  );
}
