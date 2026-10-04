import { HistoryImport } from "../components/history-import";
import { SyncStatus } from "../components/sync-status";
import { useRef, useState } from "react";
import { GarminSettings } from "../components/garmin-settings";
import { ServerConnection } from "../components/server-connection";
import {
  Button,
  Card,
  Copy,
  ErrorMessage,
  Heading,
  Muted,
  Page,
} from "../components/ui";
import { useConnection } from "../state/connection";

export default function SettingsScreen() {
  const { connection, connectionVersion, client, loading, clear } =
    useConnection();
  const [view, setView] = useState<"overview" | "server" | "forget">(
    "overview",
  );
  const [busy, setBusy] = useState(false);
  const [garminBusy, setGarminBusy] = useState(false);
  const [removed, setRemoved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lock = useRef(false);
  async function forget() {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      await clear();
      setRemoved(true);
      setView("overview");
    } catch {
      setError("Could not remove secure settings. Please try again.");
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <Page
      eyebrow="Settings"
      title={
        view === "forget"
          ? "Remove this server from your phone?"
          : view === "server"
            ? "A separate connection key."
            : "Private by default."
      }
    >
      {view === "forget" ? (
        <Card>
          <Heading>What is removed</Heading>
          <Copy>
            The saved URL and bearer token on this phone. Connected screen state
            and pending action previews are discarded.
          </Copy>
          <Muted>
            Your server’s stored plan and activities remain. This does not
            disconnect Garmin on the server.
          </Muted>
          <Button
            label="Forget server connection"
            variant="danger"
            disabled={busy}
            onPress={() => void forget()}
          />
          <Button
            label="Keep connection"
            variant="secondary"
            disabled={busy}
            onPress={() => setView("server")}
          />
        </Card>
      ) : view === "server" || !connection ? (
        <>
          {removed && <Copy>Saved connection removed.</Copy>}
          <Copy>
            This key connects the app to your server. It is not your Garmin
            password or Garmin session.
          </Copy>
          <ServerConnection />
          {connection && (
            <>
              <Muted>
                Saving a different URL or token clears connected screen state
                and pending previews.
              </Muted>
              <Button
                label="Forget connection"
                variant="danger"
                onPress={() => setView("forget")}
              />
              <Button
                label="Back to Settings"
                variant="secondary"
                onPress={() => setView("overview")}
              />
            </>
          )}
        </>
      ) : (
        <>
          <Card>
            <Heading>Your server</Heading>
            <Copy>{connection.serverUrl}</Copy>
            <Muted>
              Server token: saved securely. Test reachability in Manage
              connection.
            </Muted>
            <Button
              label="Manage connection"
              variant="secondary"
              disabled={garminBusy}
              onPress={() => setView("server")}
            />
          </Card>
          {client && (
            <GarminSettings
              key={connectionVersion}
              client={client}
              onBusyChange={setGarminBusy}
            />
          )}
          <SyncStatus />
          <HistoryImport />
          <Card>
            <Heading>Your data</Heading>
            <Copy>Your training history and plan live on your own server.</Copy>
            <Muted>
              Garmin session tokens stay on the server. Garmin passwords are
              never saved. Backup and restore belong in the operator guide.
            </Muted>
          </Card>
        </>
      )}
      <ErrorMessage message={error} />
      {loading && <Muted>Loading secure settings...</Muted>}
    </Page>
  );
}
