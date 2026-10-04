import { Client } from "../api/client";
import { useQuery } from "../state/query";
import { Card, Copy, Heading, Muted, NavLink, QueryState } from "./ui";

const load = (client: Client) => client.proposeDaily();

export function DailyRecovery() {
  const query = useQuery(load, true);
  const proposal = query.data;
  return (
    <Card>
      <Heading>Recovery for tomorrow</Heading>
      <QueryState {...query} />
      {proposal && (
        <>
          <Muted>Recovery day: {proposal.day}</Muted>
          <Copy>
            Training Readiness:{" "}
            {proposal.readiness?.training_readiness ?? "unavailable"}
          </Copy>
          <Copy>
            Sleep score: {proposal.readiness?.sleep_score ?? "unavailable"}
          </Copy>
          <Copy>HRV: {proposal.readiness?.hrv_status ?? "unavailable"}</Copy>
          {proposal.readiness && (
            <Muted>Fetched {proposal.readiness.fetched_at}</Muted>
          )}
          {proposal.reasons.map((reason) => (
            <Copy key={reason}>{reason}</Copy>
          ))}
          {proposal.after && (
            <NavLink href="/actions" label="Review tomorrow's change" />
          )}
        </>
      )}
    </Card>
  );
}
