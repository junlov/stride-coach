import { useCallback, useEffect, useRef, useState } from "react";
import { Client, Schema } from "../api/client";
import { useConnection } from "../state/connection";
import { useQuery } from "../state/query";
import { Button, Card, Copy, ErrorMessage, Heading, Muted } from "./ui";

type Range = Schema<"HistoryRequest">["range"];
const choices: [Range, string][] = [
  ["12-weeks", "12 weeks"],
  ["6-months", "6 months"],
  ["everything", "Everything"],
];

// Shared by Settings and the first-run wizard's post-Garmin import step.
export function HistoryImport(props: { onComplete?: () => void }) {
  const { connectionVersion } = useConnection();
  return <HistoryImportSession key={connectionVersion} {...props} />;
}

function HistoryImportSession({ onComplete }: { onComplete?: () => void }) {
  const { client, refresh } = useConnection();
  const requestVersion = useRef(0);
  const load = useCallback(async (api: Client) => {
    const version = ++requestVersion.current;
    const status = await api.syncStatus();
    return { version, job: status.history ?? null };
  }, []);
  const query = useQuery(load);
  const [job, setJob] = useState<Schema<"SyncAttempt"> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lock = useRef(false);
  useEffect(() => {
    if (query.data?.version === requestVersion.current && !lock.current)
      setJob(query.data.job);
  }, [query.data]);
  const current = job;
  const done = useRef<string | null>(null);
  useEffect(() => {
    if (current?.result === "success" && done.current !== current.id) {
      done.current = current.id;
      onComplete?.();
    }
  }, [current, onComplete]);
  useEffect(() => {
    if (!client || current?.result !== "running") return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const version = ++requestVersion.current;
      try {
        const status = await client!.syncStatus();
        if (active && version === requestVersion.current && !lock.current) {
          setJob(status.history ?? null);
          setError(null);
          if (status.history?.result !== "running") {
            refresh();
            return;
          }
        }
      } catch (e) {
        if (active && version === requestVersion.current && !lock.current)
          setError((e as Error).message);
        if (active) timer = setTimeout(poll, 5000);
        return;
      }
      if (active) timer = setTimeout(poll, 2000);
    }
    timer = setTimeout(poll, 2000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
    // Refresh is a context callback; polling is scoped to this client and job.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, current?.id, current?.result]);
  async function start(range: Range) {
    if (!client || lock.current) return;
    lock.current = true;
    requestVersion.current++;
    setBusy(true);
    setError(null);
    try {
      setJob(await client.importHistory(range));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      requestVersion.current++;
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <Card>
      <Heading>Import past runs</Heading>
      <Copy>
        Bring your Garmin history into your fitness estimate before creating a
        plan.
      </Copy>
      <Muted>
        Connect Garmin first. Imports continue on your server when you leave
        this screen.
      </Muted>
      {query.loading && <Muted>Checking import progress...</Muted>}
      {choices.map(([range, label]) => (
        <Button
          key={range}
          label={`Import ${label}`}
          disabled={!client || busy || current?.result === "running"}
          onPress={() => void start(range)}
        />
      ))}
      {current && (
        <Copy>
          {current.activity_count} runs imported ·{" "}
          {current.result === "success"
            ? "Complete"
            : current.result === "running"
              ? "Importing..."
              : "Paused"}
        </Copy>
      )}
      {current?.result === "error" && current.history_range && (
        <Button
          label="Resume import"
          disabled={busy}
          onPress={() => void start(current.history_range!)}
        />
      )}
      <ErrorMessage message={error ?? current?.error ?? query.error} />
      {query.error && (
        <Button label="Retry import status" onPress={query.retry} />
      )}
    </Card>
  );
}
