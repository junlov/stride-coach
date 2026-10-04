import { useCallback, useState } from "react";
import { Client } from "../api/client";
import {
  Button,
  Card,
  ConnectionGate,
  Copy,
  Muted,
  NavLink,
  Page,
  QueryState,
} from "../components/ui";
import { shiftDay, WeekDays, WeekSummary } from "../components/week";
import { localDay, weekForDate } from "../dates";
import { useConnection } from "../state/connection";
import { useQuery } from "../state/query";
export default function WeekScreen() {
  const { connectionVersion } = useConnection();
  return <ConnectedWeek key={connectionVersion} />;
}
function ConnectedWeek() {
  const [selected, setSelected] = useState<number | null>(null);
  const load = useCallback(
    async (client: Client) => {
      const [plan, status] = await Promise.all([
        client.plan(),
        client.status(),
      ]);
      const weeks = status.weeks.map((w) => w.week).sort((a, b) => a - b);
      const current = weekForDate(plan.setup.start);
      const number =
        selected !== null && weeks.includes(selected)
          ? selected
          : weeks.includes(current)
            ? current
            : weeks[0];
      return {
        plan,
        status,
        weeks,
        number,
        week: number === undefined ? null : await client.week(number),
      };
    },
    [selected],
  );
  const query = useQuery(load, true);
  const data = query.data;
  return (
    <Page
      title="A week in balance."
      eyebrow={data?.number ? `Week ${data.number}` : "Your week"}
    >
      <ConnectionGate>
        <QueryState {...query} />
        {data && (
          <>
            {data.week && data.number !== undefined ? (
              <>
                <Card>
                  <WeekSummary metrics={data.week.metrics} />
                </Card>
                <Button
                  variant="secondary"
                  label="Previous week"
                  disabled={data.weeks.indexOf(data.number) <= 0}
                  onPress={() =>
                    setSelected(
                      data.weeks[data.weeks.indexOf(data.number!) - 1],
                    )
                  }
                />
                <Button
                  variant="secondary"
                  label="Next week"
                  disabled={
                    data.weeks.indexOf(data.number) >= data.weeks.length - 1
                  }
                  onPress={() =>
                    setSelected(
                      data.weeks[data.weeks.indexOf(data.number!) + 1],
                    )
                  }
                />
                <WeekDays
                  week={data.week}
                  start={shiftDay(data.plan.setup.start, (data.number - 1) * 7)}
                  today={localDay()}
                />
                <NavLink
                  href={{
                    pathname: "/actions",
                    params: { week: String(data.number) },
                  }}
                  label="Review Garmin changes"
                />
              </>
            ) : (
              <Copy>No training weeks yet.</Copy>
            )}
            <Muted>
              {data.status.sync
                ? `Garmin coverage through ${data.status.sync.until}`
                : "Activities have not been synced yet"}
            </Muted>
            <Muted>
              Individual recorded runs and unmatched activities are not
              available from your server.
            </Muted>
          </>
        )}
      </ConnectionGate>
    </Page>
  );
}
