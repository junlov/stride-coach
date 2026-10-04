import { useCallback, useRef, useState } from "react";
import { useFocusEffect } from "expo-router";
import { Client, Schema } from "../api/client";
import { useQuery } from "../state/query";
import { Button, Card, Copy, ErrorMessage, Field, Heading, Muted } from "./ui";

export function GarminSettings({ client }: { client: Client }) {
  const load = useCallback((api: Client) => api.garminStatus(), []);
  const query = useQuery(load);
  const [status, setStatus] = useState<Schema<"GarminStatus"> | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lock = useRef(false);
  const current = status ?? query.data;
  useFocusEffect(
    useCallback(() => {
      setStatus(null);
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
    const submittedPassword = password;
    const submittedCode = code;
    setPassword("");
    setCode("");
    const pending = challenge;
    setChallenge(null);
    try {
      if (action === "logout") {
        setStatus(await client.garminLogout());
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

  return (
    <Card>
      <Heading>Garmin</Heading>
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
        label="Refresh Garmin status"
        disabled={busy || query.loading}
        onPress={() => {
          setStatus(null);
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
      <Button
        label="Disconnect Garmin"
        onPress={() => void run("logout")}
        disabled={busy}
      />
      {busy && <Muted>Waiting for Garmin...</Muted>}
    </Card>
  );
}
