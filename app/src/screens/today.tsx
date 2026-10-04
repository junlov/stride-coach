import { SyncStatus } from "../components/sync-status";
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
  Metrics,
  NavLink,
} from "../components/ui";
import { WeekDays, shiftDay } from "../components/week";
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
  const query = useQuery(loadToday, true);
  const data = query.data;
  const todayWorkouts =
    data?.week?.workouts.filter(({ workout }) => workout.day === data.today) ??
    [];
  const next = data?.plan.workouts
    .filter((w) => w.day > data.today)
    .sort((a, b) => a.day.localeCompare(b.day))[0];
  return (
    <Page
      title={
        !data?.week
          ? "Your next stride"
          : todayWorkouts.length
            ? todayWorkouts.every(({ workout }) => workout.kind === "easy")
              ? "Make room for easy."
              : "Make room for running."
            : "Recovery is training, too."
      }
      eyebrow="Your daily coach"
    >
      <ConnectionGate>
        <SyncStatus />
        <QueryState {...query} />
        {data && (
          <>
            <Muted>
              {data.today} · {data.plan.setup.goal}
            </Muted>
            {todayWorkouts.length ? (
              <Muted>Your workout is ready below.</Muted>
            ) : (
              <Card>
                <Heading>No run planned</Heading>
                <Copy>
                  {data.number < 1
                    ? `Your plan starts ${data.plan.setup.start}.`
                    : data.today > data.plan.setup.race_date
                      ? "Your plan has ended. Review your progress or set a new goal."
                      : !data.week
                        ? "No workouts scheduled this week."
                        : "Rest day. Make room for recovery."}
                </Copy>
              </Card>
            )}
            {!todayWorkouts.length && next && (
              <Card>
                <Heading>Up next · {next.day}</Heading>
                <Copy>{next.name}</Copy>
              </Card>
            )}
            {todayWorkouts.map(({ workout }) => (
              <WorkoutCard
                key={workout.id}
                workout={workout}
                hero
                match={data.week?.metrics.matches.find(
                  (m) => m.workout_id === workout.id,
                )}
              >
                <NavLink
                  primary
                  href={{
                    pathname: "/actions",
                    params: { week: String(data.number) },
                  }}
                  label="Send this week to Garmin"
                />
              </WorkoutCard>
            ))}
            <NavLink href="/week" label="See this week" />
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
                <Metrics
                  items={[
                    {
                      value: Math.round(data.week.metrics.completed_minutes),
                      label: "recorded min",
                    },
                    {
                      value: Math.round(data.week.metrics.planned_minutes),
                      label: "planned min",
                    },
                  ]}
                />
                <WeekDays
                  week={data.week}
                  start={shiftDay(data.plan.setup.start, (data.number - 1) * 7)}
                  today={data.today}
                />
              </>
            )}
            <Button variant="secondary" label="Refresh" onPress={query.retry} />
          </>
        )}
      </ConnectionGate>
    </Page>
  );
}
