import { useCallback, useRef, useState } from "react";
import { Link, useFocusEffect } from "expo-router";
import { Schema } from "../api/client";
import {
  Button,
  Card,
  ConnectionGate,
  Copy,
  ErrorMessage,
  Field,
  Heading,
  Muted,
  Page,
  styles,
} from "../components/ui";
import { useConnection } from "../state/connection";

type Preview =
  | { kind: "adapt"; adjustment: Schema<"Adjustment">; week: number }
  | { kind: "push" | "remove"; writes: Schema<"WriteResult">[]; week?: number };
function Writes({ results }: { results: Schema<"WriteResult">[] }) {
  return (
    <>
      {results.length === 0 && <Copy>No workouts to change.</Copy>}
      {results.map((item, index) => (
        <Card key={index}>
          <Heading>{item.action}</Heading>
          <Copy>
            {item.date ?? "No date"}
            {item.workout_id ? ` · ${item.workout_id}` : ""}
          </Copy>
          {item.remote_id && <Muted>Garmin ID: {item.remote_id}</Muted>}
          {item.ownership_tag && <Muted>{item.ownership_tag}</Muted>}
          {item.payload && (
            <Muted>{JSON.stringify(item.payload, null, 2)}</Muted>
          )}
        </Card>
      ))}
    </>
  );
}
export default function ActionsScreen() {
  const { client, refresh } = useConnection();
  const [week, setWeek] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [results, setResults] = useState<Schema<"WriteResult">[] | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [connectGarmin, setConnectGarmin] = useState(false);
  const lock = useRef(false);
  const generation = useRef(0);
  useFocusEffect(
    useCallback(() => {
      if (!client) return;
      generation.current++;
      setPreview(null);
      setResults(null);
      setMessage("");
      setError(null);
      setConnectGarmin(false);
      return () => {
        generation.current++;
      };
    }, [client]),
  );
  async function run(action: "sync" | "adapt" | "push" | "remove" | "confirm") {
    if (!client || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    setMessage("");
    setResults(null);
    const pending = preview;
    setPreview(null);
    const version = generation.current;
    const active = () => generation.current === version;
    try {
      if (
        action === "sync" ||
        (action === "confirm" && pending && pending.kind !== "adapt")
      ) {
        const connection = await client.garminStatus();
        if (!active()) return;
        if (!connection.connected) {
          setConnectGarmin(true);
          return;
        }
        setConnectGarmin(false);
      }
      if (action === "sync") {
        const result = await client.sync();
        if (active())
          setMessage(
            `Synced ${result.synced} activities from ${result.since} through ${result.until}.`,
          );
        refresh();
      } else if (action === "confirm" && pending) {
        if (pending.kind === "adapt") {
          const result = await client.adapt({
            week: pending.week,
            apply: true,
          });
          if (active())
            setMessage(
              `Week ${result.week} adjustment ${result.applied ? "applied" : "returned"}: ${result.before_minutes.toFixed(0)} to ${result.after_minutes.toFixed(0)} min. ${result.reasons.join(" ")}`,
            );
        } else {
          const result =
            pending.kind === "push"
              ? await client.push({
                  week: pending.week,
                  dry_run: false,
                  apply: true,
                })
              : await client.remove({ dry_run: false, apply: true });
          if (active()) {
            setResults(result);
            setMessage("Server action completed. Review each result below.");
          }
        }
        refresh();
      } else if (action !== "confirm") {
        const number = week.trim() === "" ? undefined : Number(week);
        if (
          (action === "adapt" || action === "push") &&
          number !== undefined &&
          (!/^\d+$/.test(week.trim()) ||
            !Number.isSafeInteger(number) ||
            number < 1)
        )
          throw new Error("Enter a whole week number of at least 1.");
        if (action === "adapt") {
          if (number === undefined || number < 2)
            throw new Error("Choose a week after week 1 to adapt.");
          const result = await client.propose(number);
          if (active())
            setPreview({
              kind: "adapt",
              adjustment: result.adjustment,
              week: number,
            });
        } else {
          const writes =
            action === "push"
              ? await client.push({ week: number, dry_run: true, apply: false })
              : await client.remove({ dry_run: true, apply: false });
          if (active())
            setPreview({
              kind: action,
              writes,
              week: action === "push" ? number : undefined,
            });
        }
      }
    } catch (e) {
      if (active()) {
        setError((e as Error).message);
        if (/connect Garmin/i.test((e as Error).message))
          setConnectGarmin(true);
      }
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <Page title="Coach actions">
      <ConnectionGate>
        <Card>
          <Heading>Bring your training up to date</Heading>
          <Muted>
            Sync reads your latest Garmin activities into your server. Connect
            Garmin in Settings first.
          </Muted>
          <Button
            label="Sync activities"
            onPress={() => void run("sync")}
            disabled={busy}
          />
        </Card>
        <Card>
          <Field
            label="Week (blank pushes all future weeks)"
            value={week}
            onChangeText={(value) => {
              setWeek(value);
              setPreview(null);
              setResults(null);
              setMessage("");
              setError(null);
            }}
            keyboardType="number-pad"
            editable={!busy}
          />
          <Button
            label="Preview adjustment"
            onPress={() => void run("adapt")}
            disabled={busy}
          />
          <Button
            label="Preview Garmin push"
            onPress={() => void run("push")}
            disabled={busy}
          />
          <Muted>
            Removal affects all workouts owned by this server, regardless of the
            selected week.
          </Muted>
          <Button
            label="Preview Garmin removal"
            onPress={() => void run("remove")}
            disabled={busy}
          />
        </Card>
        {busy && <Copy>Waiting for your server...</Copy>}
        {connectGarmin && (
          <Card>
            <Copy>Connect Garmin in Settings to use this action.</Copy>
            <Link href="/settings" style={styles.text}>
              Connect Garmin
            </Link>
          </Card>
        )}
        <ErrorMessage message={error} />
        {!!message && <Copy>{message}</Copy>}
        {preview && (
          <Card>
            <Heading>
              {preview.kind === "adapt"
                ? "Proposed adjustment"
                : "Garmin dry-run preview"}
            </Heading>
            {preview.kind === "adapt" ? (
              <>
                <Copy>
                  Week {preview.week}:{" "}
                  {preview.adjustment.before_minutes.toFixed(0)} to{" "}
                  {preview.adjustment.after_minutes.toFixed(0)} min
                </Copy>
                {preview.adjustment.reasons.map((reason) => (
                  <Copy key={reason}>{reason}</Copy>
                ))}
                <Muted>
                  Apply on the target week&apos;s Monday after syncing the
                  previous two complete weeks. Reductions also affect later
                  weeks. Your server rechecks eligibility when applying.
                </Muted>
              </>
            ) : (
              <>
                <Copy>
                  {preview.kind === "remove"
                    ? "Remove all owned Garmin workouts"
                    : preview.week
                      ? `Push week ${preview.week}`
                      : "Push all future weeks"}
                </Copy>
                <Writes results={preview.writes} />
                <Muted>
                  Confirming sends a live Garmin request. The server checks
                  current state again when applying.
                </Muted>
              </>
            )}
            <Button
              label={
                preview.kind === "adapt"
                  ? "Confirm adjustment"
                  : preview.kind === "push"
                    ? "Confirm live Garmin push"
                    : "Confirm live Garmin removal"
              }
              onPress={() => void run("confirm")}
              disabled={
                busy ||
                (preview.kind !== "adapt" && preview.writes.length === 0)
              }
            />
            <Button
              label="Cancel preview"
              onPress={() => setPreview(null)}
              disabled={busy}
            />
          </Card>
        )}
        {results && <Writes results={results} />}
      </ConnectionGate>
    </Page>
  );
}
