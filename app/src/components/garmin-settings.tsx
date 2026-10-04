import { useCallback, useEffect, useRef, useState } from "react";
import { useFocusEffect } from "expo-router";
import { Client, Schema } from "../api/client";
import { useQuery } from "../state/query";
import { Button, Card, Copy, ErrorMessage, Field, Heading, Muted } from "./ui";

export function GarminSettings({
  client,
  onBusyChange,
  showHeading = true,
}: {
  client: Client;
  onBusyChange?: (busy: boolean) => void;
  showHeading?: boolean;
}) {
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [disconnected, setDisconnected] = useState(false);
  const [mfaFailed, setMfaFailed] = useState(false);
  const [status, setStatus] = useState<Schema<"GarminStatus"> | null>(null);
  const load = useCallback((api: Client) => {
    setStatus(null);
    return api.garminStatus();
  }, []);
  const query = useQuery(load);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lock = useRef(false);
  const current = status ?? query.data;
  useEffect(() => {
    onBusyChange?.(busy);
  }, [busy, onBusyChange]);
  useFocusEffect(
    useCallback(() => {
      return () => {
        setPassword("");
        setCode("");
      };
    }, []),
  );

  async function run(action: "login" | "mfa" | "logout") {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    setMfaFailed(false);
    setDisconnected(false);
    const submittedPassword = password;
    const submittedCode = code;
    setPassword("");
    setCode("");
    const pending = challenge;
    setChallenge(null);
    try {
      if (action === "logout") {
        setStatus(await client.garminLogout());
        setConfirmDisconnect(false);
        setDisconnected(true);
      } else {
        const result =
          action === "login"
            ? await client.garminLogin({ email, password: submittedPassword })
            : await client.garminMfa({
                challenge_id: pending!,
                code: submittedCode,
              });
        setStatus(result);
        setChallenge(result.challenge_id ?? null);
      }
    } catch {
      if (action === "mfa") setMfaFailed(true);
      // Never display upstream text that might echo a submitted credential.
      setError(
        action === "logout"
          ? "Could not disconnect Garmin. Check the server and refresh status."
          : "Garmin connection failed. Check your details or refresh status before trying again.",
      );
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }

  if (confirmDisconnect)
    return (
      <Card>
        <Heading>Keep the plan. Close the connection.</Heading>
        <Copy>
          Disconnect the Garmin session on your server. Sync and Garmin workout
          writes will stop.
        </Copy>
        <Heading>What stays</Heading>
        <Copy>
          Your plan and stored activities remain. Workouts already sent to
          Garmin are not removed.
        </Copy>
        <Muted>
          To remove server-owned Garmin workouts, use the separate removal flow
          before disconnecting.
        </Muted>
        <ErrorMessage message={error} />
        <Button
          label="Confirm disconnect"
          variant="danger"
          disabled={busy}
          onPress={() => void run("logout")}
        />
        <Button
          label="Keep Garmin connected"
          variant="secondary"
          disabled={busy}
          onPress={() => {
            setConfirmDisconnect(false);
            setError(null);
          }}
        />
      </Card>
    );

  return (
    <Card>
      {showHeading && (
        <Heading>
          {current?.connected
            ? "Connected through your server."
            : challenge
              ? "One more step."
              : "Bring your runs together."}
        </Heading>
      )}
      <Muted>
        Your server connects to Garmin. This session is separate from the app’s
        server token.
      </Muted>
      {disconnected && (
        <Copy>
          Garmin disconnected. Your plan, stored activities and existing Garmin
          workouts are unchanged.
        </Copy>
      )}
      {(query.error || mfaFailed) && (
        <>
          <Heading>
            {mfaFailed ? "Code not accepted" : "Reconnect when you are ready."}
          </Heading>
          <Muted>
            {mfaFailed
              ? "Verification failed or expired. Restart Garmin sign-in to request a new code. Your plan is unchanged."
              : "Refresh status to check the session, or sign in again. Your plan and stored activities remain on the server."}
          </Muted>
        </>
      )}
      {query.loading && !status && <Muted>Checking Garmin connection...</Muted>}
      {current && (
        <Copy>
          {current.connected
            ? `Connected to Garmin${current.display_name ? ` as ${current.display_name}` : ""}.`
            : "Garmin is not connected."}
        </Copy>
      )}
      {current?.expires_at && (
        <Muted>
          Access token expires:{" "}
          {new Date(current.expires_at * 1000).toLocaleString()}
        </Muted>
      )}
      <ErrorMessage message={error ?? (status ? null : query.error)} />
      <Button
        variant="secondary"
        label="Refresh Garmin status"
        disabled={busy || query.loading}
        onPress={() => {
          setError(null);
          query.retry();
        }}
      />
      {!current?.connected &&
        (challenge ? (
          <>
            <Copy>
              Enter the MFA code Garmin sent you. The challenge expires after
              five minutes.
            </Copy>
            <Field
              label="Garmin MFA code"
              value={code}
              onChangeText={setCode}
              autoCapitalize="none"
              autoCorrect={false}
              secureTextEntry
              editable={!busy}
            />
            <Button
              label="Complete Garmin connection"
              onPress={() => void run("mfa")}
              disabled={busy || !code.trim()}
            />
            <Button
              label="Restart Garmin sign-in"
              variant="secondary"
              disabled={busy}
              onPress={() => {
                setChallenge(null);
                setCode("");
                setError(null);
              }}
            />
          </>
        ) : (
          <>
            <Field
              label="Garmin email"
              value={email}
              onChangeText={setEmail}
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
              editable={!busy}
            />
            <Field
              label="Garmin password"
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
              editable={!busy}
            />
            <Muted>
              Your password is sent once to your server for login and is never
              saved. Only Garmin session tokens are stored on the server.
            </Muted>
            <Button
              label="Connect Garmin"
              onPress={() => void run("login")}
              disabled={busy || !email.trim() || !password}
            />
          </>
        ))}
      {current?.connected && (
        <>
          <GarminCoverage />
          <Muted>
            Sync after a run from Actions to bring activities into your week. A
            connected session does not mean your activities have been synced.
          </Muted>
          <Button
            label="Disconnect Garmin"
            variant="danger"
            onPress={() => {
              setError(null);
              setConfirmDisconnect(true);
            }}
            disabled={busy}
          />
        </>
      )}
      {!current?.connected && (query.error || mfaFailed || disconnected) && (
        <Button
          label={mfaFailed ? "Restart Garmin sign-in" : "Reconnect Garmin"}
          variant="secondary"
          disabled={busy}
          onPress={() => {
            setChallenge(null);
            setCode("");
            setPassword("");
            setError(null);
            setMfaFailed(false);
            setDisconnected(false);
          }}
        />
      )}
      {busy && <Muted>Waiting for Garmin...</Muted>}
    </Card>
  );
}

function GarminCoverage() {
  const load = useCallback(async (api: Client) => {
    return (await api.status()).sync;
  }, []);
  const query = useQuery(load);
  if (query.loading) return <Muted>Checking activity coverage...</Muted>;
  if (query.error)
    return (
      <>
        <Muted>
          Activity coverage is unavailable. A Garmin connection alone does not
          confirm a sync.
        </Muted>
        <Button
          label="Retry activity coverage"
          variant="secondary"
          onPress={query.retry}
        />
      </>
    );
  return query.data ? (
    <>
      <Copy>Coverage starts: {query.data.since}</Copy>
      <Copy>Coverage through: {query.data.until}</Copy>
      <Muted>
        Dates use the server’s timezone. Coverage dates describe activity
        history, not the time of the last successful sync.
      </Muted>
    </>
  ) : (
    <Muted>No activity sync coverage recorded yet.</Muted>
  );
}
