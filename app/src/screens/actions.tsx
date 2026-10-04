import { SyncStatus } from "../components/sync-status";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocalSearchParams, useFocusEffect } from "expo-router";
import { ApiError, Schema } from "../api/client";
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
  Badge,
  Metrics,
  Notice,
  NavLink,
} from "../components/ui";
import { GarminPayload } from "../components/garmin-payload";
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
          {item.payload && <GarminPayload payload={item.payload} />}
          {item.remote_id && <Muted>Garmin ID: {item.remote_id}</Muted>}
          {item.ownership_tag && <Muted>{item.ownership_tag}</Muted>}
        </Card>
      ))}
    </>
  );
}
export default function ActionsScreen() {
  const { connectionVersion } = useConnection();
  return <ConnectedActions key={connectionVersion} />;
}
function ConnectedActions() {
  const { client, refresh } = useConnection();
  const params = useLocalSearchParams<{ week?: string }>();
  const [week, setWeek] = useState(
    typeof params.week === "string" ? params.week : "",
  );
  const [preview, setPreview] = useState<Preview | null>(null);
  const [results, setResults] = useState<Schema<"WriteResult">[] | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [connectGarmin, setConnectGarmin] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const [inspection, setInspection] = useState<Schema<"Status"> | null>(null);
  const [applied, setApplied] = useState<Schema<"Adjustment"> | null>(null);
  const lock = useRef(false);
  const generation = useRef(0);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useFocusEffect(
    useCallback(() => {
      if (!client) return;
      generation.current++;
      if (typeof params.week === "string") setWeek(params.week);
      setPreview(null);
      setResults(null);
      setMessage("");
      setError(null);
      setConnectGarmin(false);
      return () => {
        generation.current++;
      };
    }, [client, params.week]),
  );
  async function run(action: "sync" | "adapt" | "push" | "remove" | "confirm") {
    if (!client || lock.current || unknown) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    setMessage("");
    setResults(null);
    setApplied(null);
    const pending = preview;
    setPreview(null);
    const version = generation.current;
    const active = () => mounted.current && generation.current === version;
    let writeStarted = false;
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
        writeStarted = true;
        const result = await client.sync();
        if (active())
          setMessage(
            `Synced ${result.synced} activities from ${result.since} through ${result.until}.`,
          );
        if (mounted.current) refresh();
      } else if (action === "confirm" && pending) {
        writeStarted = true;
        if (pending.kind === "adapt") {
          const result = await client.adapt({
            week: pending.week,
            apply: true,
          });
          if (active()) {
            setApplied(result);
            setMessage(
              `Week ${result.week} adjustment ${result.applied ? "applied" : "returned"}: ${result.before_minutes.toFixed(0)} to ${result.after_minutes.toFixed(0)} min. ${result.reasons.join(" ")}`,
            );
          }
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
        if (mounted.current) refresh();
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
      // Preserve an uncertain write even if the runner left the screen in flight.
      const rejected =
        e instanceof ApiError &&
        e.status !== undefined &&
        e.status >= 400 &&
        e.status < 500;
      if (mounted.current && writeStarted && !rejected) {
        setUnknown(true);
        setInspection(null);
      }
      if (active()) {
        setError((e as Error).message);
        if (/connect Garmin/i.test((e as Error).message))
          setConnectGarmin(true);
      }
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function inspect() {
    if (!client || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    setInspection(null);
    const version = generation.current;
    try {
      const state = await client.status();
      if (mounted.current && version === generation.current)
        setInspection(state);
    } catch (e) {
      if (mounted.current && version === generation.current)
        setError((e as Error).message);
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <Page title="Ready for your next run." eyebrow="Coach actions">
      <ConnectionGate>
        <SyncStatus />
        <Card>
          <Heading>Bring your training up to date</Heading>
          <Muted>
            Sync reads your latest Garmin activities into your server. Connect
            Garmin in Settings first.
          </Muted>
          <Button
            label="Sync activities"
            onPress={() => void run("sync")}
            disabled={busy || unknown}
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
            variant="secondary"
            label="Preview adjustment"
            onPress={() => void run("adapt")}
            disabled={busy || unknown}
          />
          <Button
            label="Preview Garmin push"
            onPress={() => void run("push")}
            disabled={busy || unknown}
          />
          <Muted>
            Removal affects all workouts owned by this server, regardless of the
            selected week.
          </Muted>
          <Button
            variant="secondary"
            label="Preview Garmin removal"
            onPress={() => void run("remove")}
            disabled={busy || unknown}
          />
        </Card>
        {busy && <Copy>Waiting for your server...</Copy>}
        {connectGarmin && (
          <Card>
            <Copy>Connect Garmin in Settings to use this action.</Copy>
            <NavLink href="/settings" label="Connect Garmin" />
          </Card>
        )}
        {unknown && (
          <Notice title="The result is unknown.">
            <Copy>
              The request may have completed. Nothing will retry automatically.
            </Copy>
            <Muted>
              Read your server state and inspect Garmin directly before
              requesting a fresh preview. A server count cannot prove which
              remote workouts changed.
            </Muted>
            <Button
              label="Inspect current state"
              variant="secondary"
              onPress={() => void inspect()}
              disabled={busy}
            />
            {inspection && (
              <>
                <Heading>Current server state</Heading>
                <Copy>
                  {inspection.scheduled_workouts} workouts tracked by this
                  server
                </Copy>
                <Muted>
                  {inspection.sync
                    ? `Activity coverage: ${inspection.sync.since} to ${inspection.sync.until}`
                    : "No sync coverage recorded"}
                </Muted>
                <Copy>
                  {inspection.adjustments.length} saved plan adjustments
                </Copy>
                <Muted>
                  The API does not return an authoritative Garmin workout list.
                  Compare in Garmin before continuing.
                </Muted>
                <Button
                  label="I checked the current state"
                  variant="secondary"
                  disabled={busy}
                  onPress={() => {
                    setUnknown(false);
                    setInspection(null);
                    setError(null);
                  }}
                />
              </>
            )}
          </Notice>
        )}
        {error && !unknown && /sync|Monday|complete weeks/i.test(error) && (
          <Notice title="Not ready to adjust yet.">
            <Copy>
              Review on the target Monday after Garmin sync covers the previous
              two complete weeks.
            </Copy>
          </Notice>
        )}
        {error && /No future workouts match/i.test(error) && (
          <Notice title="Nothing to send.">
            <Copy>
              No future workouts match this selection. There is no live action
              to confirm.
            </Copy>
          </Notice>
        )}
        {error && /Authentication failed/i.test(error) && (
          <Notice title="Your connection needs attention.">
            <Copy>
              Your server token was rejected. Update it in Settings before
              continuing.
            </Copy>
            <NavLink href="/settings" label="Open Settings" />
          </Notice>
        )}
        <ErrorMessage message={error} />
        {!!message && (
          <Notice
            title={
              applied?.applied
                ? "Why the plan changed"
                : results
                  ? "Garmin result"
                  : "Training updated"
            }
          >
            <Copy>{message}</Copy>
            {applied?.applied && (
              <Muted>
                Garmin is unchanged. Preview Garmin changes separately.
              </Muted>
            )}
          </Notice>
        )}
        {preview && (
          <Card>
            <Badge>Review · not applied</Badge>
            <Heading>
              {preview.kind === "adapt"
                ? "Proposed adjustment"
                : "Garmin dry-run preview"}
            </Heading>
            {preview.kind === "adapt" ? (
              <>
                <Metrics
                  items={[
                    {
                      value: preview.adjustment.before_minutes.toFixed(0),
                      label: "before min",
                    },
                    {
                      value: preview.adjustment.after_minutes.toFixed(0),
                      label: "proposed min",
                    },
                  ]}
                />
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
                {preview.writes.length === 0 && (
                  <Notice
                    title={
                      preview.kind === "push"
                        ? "Nothing to send."
                        : "Nothing to remove."
                    }
                  >
                    <Copy>
                      There are no changes in this preview. No live request is
                      available.
                    </Copy>
                  </Notice>
                )}
                {preview.kind === "remove" && (
                  <Notice title="Across all weeks">
                    <Copy>
                      These ownership candidates include planned workouts that
                      were never uploaded. Only matching Garmin workouts will be
                      removed. The week field does not limit removal. Your plan
                      and recorded activities remain.
                    </Copy>
                  </Notice>
                )}
                <Writes results={preview.writes} />
                <Muted>
                  Confirming sends a live Garmin request. The server checks
                  current state again when applying.
                </Muted>
              </>
            )}
            <Notice
              title={
                preview.kind === "remove"
                  ? `Remove Garmin matches for ${preview.writes.length} ownership candidates?`
                  : preview.kind === "push"
                    ? `Send ${preview.writes.length} workouts?`
                    : "Confirm plan adjustment"
              }
            >
              <Muted>
                Confirm only after reviewing. Current server state is
                recalculated and changes from another client can change the
                result.
              </Muted>
            </Notice>
            <Button
              variant={preview.kind === "remove" ? "danger" : "primary"}
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
                unknown ||
                (preview.kind !== "adapt" && preview.writes.length === 0)
              }
            />
            <Button
              variant="secondary"
              label="Cancel preview"
              onPress={() => setPreview(null)}
              disabled={busy || unknown}
            />
          </Card>
        )}
        {results && <Writes results={results} />}
      </ConnectionGate>
    </Page>
  );
}
