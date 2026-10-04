import { Client } from "../api/client";
import { useQuery } from "../state/query";
import { Copy, ErrorMessage, Muted, Button } from "./ui";
const loadSync = (client: Client) => client.syncStatus();
export function SyncStatus() {
  const query = useQuery(loadSync);
  const status = query.data;
  return (
    <>
      {query.loading && <Muted>Checking last sync...</Muted>}
      {status && (
        <Copy>
          {status.last_success?.finished_at
            ? `Last synced ${new Date(status.last_success.finished_at).toLocaleString()}`
            : "No completed sync yet."}
        </Copy>
      )}
      {status?.latest?.result === "running" && (
        <Muted>Sync in progress...</Muted>
      )}
      <ErrorMessage message={status?.latest?.error ?? query.error} />
      {query.error && (
        <Button label="Refresh sync status" onPress={query.retry} />
      )}
    </>
  );
}
