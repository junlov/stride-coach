import { useState } from "react";
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
  Badge,
  NavLink,
  Notice,
} from "../components/ui";
import { WorkoutCard, workoutMinutes } from "../components/workout";
import { useQuery } from "../state/query";
async function loadPlan(client: Client) {
  const [plan, status] = await Promise.all([client.plan(), client.status()]);
  return { ...plan, status };
}
export default function PlanScreen() {
  const query = useQuery(loadPlan);
  const [expanded, setExpanded] = useState<number | null>(null);
  return (
    <Page title="Build your staying power." eyebrow="Your plan">
      <ConnectionGate>
        <QueryState {...query} />
        {query.data && (
          <>
            <Copy>
              {query.data.setup.goal} · {query.data.setup.start} to{" "}
              {query.data.setup.race_date}
            </Copy>
            <Muted>
              {query.data.setup.days_per_week} days per week · Fitness:{" "}
              {query.data.fitness.source}
            </Muted>
            {query.data.warnings?.map((warning) => (
              <Copy key={warning}>{warning}</Copy>
            ))}
            {[
              ...new Set(query.data.workouts.map((workout) => workout.week)),
            ].map((number) => {
              const workouts = query.data!.workouts.filter(
                (workout) => workout.week === number,
              );
              return (
                <Card key={number}>
                  <Badge>
                    {workouts[0]?.phase}
                    {workouts.some((w) => w.cutback) ? " · Cutback" : ""}
                  </Badge>
                  <Heading>Week {number}</Heading>
                  <Muted>
                    {workouts.length} sessions ·{" "}
                    {Math.round(
                      workouts.reduce(
                        (sum, workout) => sum + workoutMinutes(workout),
                        0,
                      ),
                    )}{" "}
                    min
                  </Muted>
                  <Button
                    variant="secondary"
                    label={`${expanded === number ? "Hide" : "View"} week ${number}`}
                    onPress={() =>
                      setExpanded(expanded === number ? null : number)
                    }
                  />
                  {expanded === number &&
                    workouts.map((workout) => (
                      <WorkoutCard key={workout.id} workout={workout} />
                    ))}
                </Card>
              );
            })}
            <NavLink href="/actions" label="Manage Garmin workouts" />
            <Heading>Why the plan changed</Heading>
            {query.data.status.adjustments.length === 0 && (
              <Muted>No saved adjustments yet.</Muted>
            )}
            {query.data.status.adjustments.map((adjustment, i) => (
              <Notice
                key={i}
                title={`Week ${adjustment.week} · ${adjustment.applied ? "Applied" : "Proposed"}`}
              >
                <Copy>
                  {adjustment.before_minutes.toFixed(0)} →{" "}
                  {adjustment.after_minutes.toFixed(0)} min
                </Copy>
                {adjustment.reasons.map((reason) => (
                  <Copy key={reason}>{reason}</Copy>
                ))}
                <Muted>
                  Adjusting the plan does not send Garmin workouts. Review
                  Garmin changes separately.
                </Muted>
              </Notice>
            ))}
          </>
        )}
      </ConnectionGate>
    </Page>
  );
}
