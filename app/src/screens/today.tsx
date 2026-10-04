import { Client } from "../api/client";
import {
  Button,
  Card,
  ConnectionGate,
  Copy,
  Heading,
  Muted,
  Page,
  QueryState,
} from "../components/ui";
import { WorkoutCard } from "../components/workout";
import { localDay, weekForDate } from "../dates";
import { useQuery } from "../state/query";
async function loadToday(client: Client) {
  const [status, plan] = await Promise.all([client.status(), client.plan()]);
  const today = localDay();
  const number = weekForDate(plan.setup.start, today);
  const inPlan =
    today <= plan.setup.race_date &&
    status.weeks.some((week) => week.week === number);
  return {
    status,
    plan,
    today,
    number,
    week: inPlan ? await client.week(number) : null,
  };
}
export default function TodayScreen() {
  const query = useQuery(loadToday);
  const data = query.data;
  const todayWorkouts =
    data?.week?.workouts.filter(({ workout }) => workout.day === data.today) ??
    [];
  return (
    <Page title="Your next stride">
      <ConnectionGate>
        <QueryState {...query} />
        {data && (
          <>
            <Muted>
              {data.today} · {data.plan.setup.goal}
            </Muted>
            <Card>
              <Heading>Today</Heading>
              {todayWorkouts.length ? (
                <Copy>Your workout is ready below.</Copy>
              ) : (
                <Copy>
                  {data.number < 1
                    ? `Your plan starts ${data.plan.setup.start}.`
                    : !data.week
                      ? "Your plan has ended. Review your progress or set a new goal."
                      : "Rest day. Make room for recovery."}
                </Copy>
              )}
            </Card>
            {todayWorkouts.map(({ workout }) => (
              <WorkoutCard key={workout.id} workout={workout} />
            ))}
            <Muted>
              {data.status.scheduled_workouts} workouts scheduled in Garmin ·{" "}
              {data.status.sync
                ? `Last sync covers through ${data.status.sync.until}`
                : "Activities have not been synced yet"}
            </Muted>
            {data.week && (
              <>
                <Heading>Week {data.number}</Heading>
                <Copy>
                  {Math.round(data.week.metrics.compliance * 100)}% complete ·{" "}
                  {data.week.metrics.matched_sessions}/
                  {data.week.metrics.planned_sessions} sessions
                </Copy>
                {data.week.workouts.map(({ workout }) => (
                  <WorkoutCard key={workout.id} workout={workout} />
                ))}
              </>
            )}
            <Button label="Refresh" onPress={query.retry} />
          </>
        )}
      </ConnectionGate>
    </Page>
  );
}
