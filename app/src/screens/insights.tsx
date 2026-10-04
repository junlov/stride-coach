import { View } from "react-native";
import { useTheme } from "../theme";
import { Client } from "../api/client";
import {
  Card,
  ConnectionGate,
  Copy,
  Heading,
  Muted,
  Page,
  QueryState,
  Metrics,
  Notice,
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
  const { colors } = useTheme();
  const weeks = query.data?.compliance ?? [];
  const maxMinutes = Math.max(
    1,
    ...weeks.flatMap((w) => [w.planned_minutes, w.completed_minutes]),
  );
  return (
    <Page title="Steady takes you far." eyebrow="Training progress">
      <ConnectionGate>
        <QueryState {...query} />
        <Muted>
          Compliance matches completed runs to planned sessions. TRIMP estimates
          training load from heart rate and duration.
        </Muted>
        {weeks.length > 0 && (
          <Card>
            <Heading>Weekly minutes</Heading>
            <Muted>Pale: planned · solid: recorded</Muted>
            {weeks.map((week) => (
              <View
                key={week.week}
                style={{ gap: 4 }}
                accessible
                accessibilityLabel={`Week ${week.week}: ${Math.round(week.planned_minutes)} planned minutes, ${Math.round(week.completed_minutes)} recorded minutes`}
              >
                <Muted>
                  W{week.week} · {Math.round(week.planned_minutes)} planned /{" "}
                  {Math.round(week.completed_minutes)} recorded
                </Muted>
                <View
                  style={{
                    height: 10,
                    width: `${(week.planned_minutes / maxMinutes) * 100}%`,
                    backgroundColor: colors.muted,
                    opacity: 0.45,
                  }}
                />
                <View
                  style={{
                    height: 10,
                    width: `${(week.completed_minutes / maxMinutes) * 100}%`,
                    backgroundColor: colors.text,
                  }}
                />
              </View>
            ))}
          </Card>
        )}
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
              <Metrics
                items={[
                  {
                    value: load ? load.trimp.toFixed(1) : "Unavailable",
                    label: "known TRIMP",
                  },
                  {
                    value: Math.round(week.completed_minutes),
                    label: "recorded min",
                  },
                ]}
              />
              <Copy>
                Training load: {load ? load.trimp.toFixed(1) : "Unavailable"}{" "}
                TRIMP
              </Copy>
              {!!load?.missing_hr && (
                <Notice title="Load is incomplete">
                  <Muted>
                    {load.missing_hr} runs missing heart rate. Load is
                    incomplete.
                  </Muted>
                  <Copy>
                    These runs count toward volume. Their heart-rate load is
                    unavailable, not zero.
                  </Copy>
                </Notice>
              )}
            </Card>
          );
        })}
        {query.data && (
          <Muted>
            Distance history and the fraction of recorded minutes with heart
            rate are not available from your server.
          </Muted>
        )}
      </ConnectionGate>
    </Page>
  );
}
