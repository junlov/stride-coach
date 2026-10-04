import { Client } from "../api/client";
import {
  Card,
  ConnectionGate,
  Copy,
  Heading,
  Muted,
  Page,
  QueryState,
} from "../components/ui";
import { useQuery } from "../state/query";
async function loadInsights(client: Client) {
  const [load, compliance] = await Promise.all([
    client.load(),
    client.compliance(),
  ]);
  return { load, compliance };
}
export default function InsightsScreen() {
  const query = useQuery(loadInsights);
  return (
    <Page title="Training progress">
      <ConnectionGate>
        <QueryState {...query} />
        <Muted>
          Compliance matches completed runs to planned sessions. TRIMP estimates
          training load from heart rate and duration.
        </Muted>
        {query.data?.compliance.length === 0 && (
          <Copy>No training weeks yet.</Copy>
        )}
        {query.data?.compliance.map((week) => {
          const load = query.data!.load.find((item) => item.week === week.week);
          return (
            <Card key={week.week}>
              <Heading>Week {week.week}</Heading>
              <Copy>
                {Math.round(week.compliance * 100)}% complete ·{" "}
                {week.matched_sessions}/{week.planned_sessions} sessions
              </Copy>
              <Copy>
                {week.completed_minutes.toFixed(0)} of{" "}
                {week.planned_minutes.toFixed(0)} planned min
              </Copy>
              <Copy>
                Training load: {load ? load.trimp.toFixed(1) : "Unavailable"}{" "}
                TRIMP
              </Copy>
              {!!load?.missing_hr && (
                <Muted>
                  {load.missing_hr} runs missing heart rate. Load is incomplete.
                </Muted>
              )}
            </Card>
          );
        })}
      </ConnectionGate>
    </Page>
  );
}
