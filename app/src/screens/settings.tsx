import { useRef, useState } from "react";
import { GarminSettings } from "../components/garmin-settings";
import { ApiError, createClient } from "../api/client";
import {
  Button,
  Card,
  Copy,
  ErrorMessage,
  Field,
  Muted,
  Page,
} from "../components/ui";
import { useConnection } from "../state/connection";
export default function SettingsScreen() {
  const {
    connection,
    connectionVersion,
    client,
    loading,
    error: storageError,
    save,
    clear,
  } = useConnection();
  const [draftUrl, setServerUrl] = useState<string | null>(null);
  const serverUrl = draftUrl ?? connection?.serverUrl ?? "";
  const [draftToken, setToken] = useState<string | null>(null);
  const token = draftToken ?? connection?.token ?? "";
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function run(action: "save" | "test" | "clear") {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setMessage("");
    setError(null);
    try {
      if (action === "save") {
        await save({ serverUrl, token });
        setMessage("Connection saved securely.");
      }
      if (action === "clear") {
        await clear();
        setServerUrl(null);
        setToken(null);
        setMessage("Saved connection removed.");
      }
      if (action === "test") {
        try {
          await createClient({ serverUrl, token }).status();
          setMessage("Connected. Authentication and status are working.");
        } catch (e) {
          if (
            e instanceof ApiError &&
            e.status === 400 &&
            /plan/i.test(e.message)
          )
            setMessage(
              "Server reached, but no plan is available. Save settings, then open Goal setup.",
            );
          else throw e;
        }
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
  const disabled = busy || loading;
  return (
    <Page title="Your server">
      <Copy>Connect to your own Stride Coach server.</Copy>
      <Card>
        <Field
          label="Server URL"
          value={serverUrl}
          onChangeText={(v) => {
            setServerUrl(v);
            setMessage("");
            setError(null);
          }}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          placeholder="https://coach.example.com"
          editable={!disabled}
        />
        <Field
          label="Bearer token"
          value={token}
          onChangeText={(v) => {
            setToken(v);
            setMessage("");
            setError(null);
          }}
          secureTextEntry
          autoCapitalize="none"
          autoCorrect={false}
          editable={!disabled}
        />
        <Muted>
          The URL and token stay in your device secure storage. Garmin session
          tokens stay on your server. Your Garmin password is never saved.
        </Muted>
        <Button
          label="Test connection"
          onPress={() => void run("test")}
          disabled={disabled}
        />
        <Button
          label="Save connection"
          onPress={() => void run("save")}
          disabled={disabled}
        />
        <Button
          label="Forget connection"
          onPress={() => void run("clear")}
          disabled={disabled}
        />
      </Card>
      {client && connection && (
        <GarminSettings key={connectionVersion} client={client} />
      )}
      <ErrorMessage message={error ?? storageError} />
      {!!message && <Copy>{message}</Copy>}
      {busy && <Muted>Working...</Muted>}
    </Page>
  );
}
