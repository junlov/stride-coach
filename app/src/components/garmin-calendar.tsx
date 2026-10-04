import { useCallback, useRef, useState } from "react";
import { useFocusEffect } from "expo-router";
import { Client, Schema } from "../api/client";
import { useConnection } from "../state/connection";
import { useQuery } from "../state/query";
import {
  Button,
  Card,
  Copy,
  ErrorMessage,
  Field,
  Heading,
  Muted,
  QueryState,
} from "./ui";
import { GarminPayload } from "./garmin-payload";

const loadSettings = (client: Client) => client.calendarSettings();
const loadStatus = (client: Client) => client.status();

export function GarminWindowSettings() {
  const { client, refresh } = useConnection();
  const query = useQuery(loadSettings);
  const [draft, setDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const lock = useRef(false);
  const value = draft ?? String(query.data?.window_days ?? 14);
  async function save() {
    if (!client || lock.current) return;
    if (!/^\d+$/.test(value) || Number(value) < 7 || Number(value) > 28) {
      setError("Choose a whole number from 7 to 28 days.");
      return;
    }
    lock.current = true;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await client.saveCalendarSettings({ window_days: Number(value) });
      setSaved(true);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <Card>
      <Heading>Garmin calendar window</Heading>
      <QueryState {...query} />
      {query.data && (
        <>
          <Field
            label="Days on Garmin (7 to 28)"
            value={value}
            keyboardType="number-pad"
            editable={!busy}
            onChangeText={(text) => {
              setDraft(text);
              setSaved(false);
            }}
          />
          <Muted>
            Default: 14 days, including today. Saving does not send or remove
            workouts. Review calendar changes in Coach actions.
          </Muted>
          <Button
            label="Save Garmin window"
            disabled={busy}
            onPress={() => void save()}
          />
        </>
      )}
      {saved && (
        <Copy>
          Window saved. Preview calendar changes before updating Garmin.
        </Copy>
      )}
      <ErrorMessage message={error} />
    </Card>
  );
}

export function GarminCalendar({
  disabled = false,
  onBusyChange,
}: {
  disabled?: boolean;
  onBusyChange?: (busy: boolean) => void;
}) {
  const { client, refresh } = useConnection();
  const query = useQuery(loadStatus, true);
  const [preview, setPreview] = useState<Schema<"CalendarResult"> | null>(null);
  const [busy, setBusy] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const lock = useRef(false);
  const generation = useRef(0);
  useFocusEffect(
    useCallback(() => {
      if (!client) return;
      generation.current++;
      setPreview(null);
      return () => {
        generation.current++;
      };
    }, [client]),
  );
  async function run(apply: boolean) {
    if (!client || lock.current || disabled || (apply && (!preview || unknown)))
      return;
    lock.current = true;
    setBusy(true);
    setError(null);
    setMessage("");
    const version = generation.current;
    const active = () => generation.current === version;
    onBusyChange?.(true);
    const reviewed = preview;
    setPreview(null);
    try {
      const result = await client.calendar(
        apply
          ? { apply: true, preview_id: reviewed!.preview_id }
          : { apply: false },
      );
      if (!active()) return;
      if (apply) {
        setMessage("Garmin calendar updated.");
        refresh();
      } else {
        setPreview(result);
        setUnknown(false);
      }
    } catch (e) {
      if (active()) setError((e as Error).message);
      if (apply) setUnknown(true);
    } finally {
      lock.current = false;
      setBusy(false);
      onBusyChange?.(false);
    }
  }
  return (
    <Card>
      <Heading>
        {query.data?.garmin_out_of_date
          ? "Garmin is out of date"
          : "Garmin calendar"}
      </Heading>
      <QueryState {...query} />
      <Muted>
        Review the next {query.data?.garmin_window_days ?? 14} days, plus owned
        stale workouts. Garmin changes only after confirmation.
      </Muted>
      <Button
        label="Preview calendar changes"
        onPress={() => void run(false)}
        disabled={busy || disabled}
      />
      {unknown && (
        <Copy>
          The previous result is uncertain. Inspect Garmin, then request a fresh
          preview before confirming again.
        </Copy>
      )}
      {busy && <Muted>Checking Garmin...</Muted>}
      <ErrorMessage message={error} />
      {!!message && <Copy>{message}</Copy>}
      {preview && (
        <>
          <Heading>Review calendar changes</Heading>
          <Copy>
            {preview.since} through {preview.until} ({preview.window_days} days)
          </Copy>
          {preview.changes.length === 0 && (
            <Copy>No Garmin changes needed.</Copy>
          )}
          {preview.changes.map((change, i) => (
            <Card key={i}>
              <Heading>{change.action}</Heading>
              <Copy>{change.date ?? "Unscheduled"}</Copy>
              {change.reason && <Copy>{change.reason}</Copy>}
              {change.payload && <GarminPayload payload={change.payload} />}
              {change.ownership_tag && <Muted>{change.ownership_tag}</Muted>}
            </Card>
          ))}
          <Muted>
            Only workouts with a Stride Coach ownership tag can be removed.
            Completed past workouts remain. Sync activities first to identify
            missed past workouts.
          </Muted>
          <Button
            label="Confirm calendar changes"
            disabled={busy || disabled || unknown}
            onPress={() => void run(true)}
          />
          <Button
            label="Cancel calendar preview"
            variant="secondary"
            disabled={busy}
            onPress={() => setPreview(null)}
          />
        </>
      )}
    </Card>
  );
}
