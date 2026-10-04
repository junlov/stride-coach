import { View } from "react-native";
import { Schema } from "../api/client";
import { Badge, Copy, Heading, Metrics, Muted } from "./ui";
import { WorkoutCard } from "./workout";
import { useTheme, spacing } from "../theme";
export function shiftDay(day: string, days: number) {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}
export function WeekSummary({ metrics }: { metrics: Schema<"Metrics"> }) {
  return (
    <>
      <Metrics
        items={[
          { value: Math.round(metrics.planned_minutes), label: "planned min" },
          {
            value: Math.round(metrics.completed_minutes),
            label: "recorded min",
          },
        ]}
      />
      <Copy>
        {Math.round(metrics.compliance * 100)}% complete ·{" "}
        {metrics.matched_sessions}/{metrics.planned_sessions} sessions
      </Copy>
      <Muted>
        Matches are inferred. Recorded minutes can include extra runs.
      </Muted>
    </>
  );
}
export function WeekDays({
  week,
  start,
  today,
}: {
  week: Schema<"WeekView">;
  start: string;
  today: string;
}) {
  const { colors } = useTheme();
  return (
    <>
      {Array.from({ length: 7 }, (_, i) => shiftDay(start, i)).map((day) => {
        const workouts = week.workouts.filter(
          (item) => item.workout.day === day,
        );
        return (
          <View
            key={day}
            style={{
              gap: spacing.md,
              paddingVertical: spacing.md,
              borderTopWidth: 0.5,
              borderColor: colors.border,
            }}
          >
            <Heading>
              {new Date(`${day}T12:00:00`).toLocaleDateString(undefined, {
                weekday: "short",
                month: "short",
                day: "numeric",
              })}
              {day === today ? " · Today" : ""}
            </Heading>
            {workouts.length ? (
              workouts.map(({ workout }) => (
                <View key={workout.id} style={{ gap: spacing.sm }}>
                  <Badge>
                    {week.metrics.matches.some(
                      (m) => m.workout_id === workout.id,
                    )
                      ? "Matched"
                      : day < today
                        ? "No match recorded"
                        : "Planned"}
                  </Badge>
                  <WorkoutCard
                    workout={workout}
                    match={week.metrics.matches.find(
                      (m) => m.workout_id === workout.id,
                    )}
                  />
                </View>
              ))
            ) : (
              <>
                <Copy>Rest planned</Copy>
                <Muted>Recovery is part of your plan.</Muted>
              </>
            )}
          </View>
        );
      })}
    </>
  );
}
