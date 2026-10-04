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
} from "../components/ui";
import { WorkoutCard } from "../components/workout";
import { useQuery } from "../state/query";
const loadPlan = (client: Client) => client.plan();
export default function PlanScreen() {
  const query = useQuery(loadPlan);
  const [expanded, setExpanded] = useState<number | null>(null);
  return (
    <Page title="Your plan">
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
                  <Heading>Week {number}</Heading>
                  <Muted>
                    {workouts.length} sessions ·{" "}
                    {Math.round(
                      workouts.reduce(
                        (sum, workout) =>
                          sum +
                          workout.steps.reduce(
                            (n, step) => n + step.minutes,
                            0,
                          ),
                        0,
                      ),
                    )}{" "}
                    min
                  </Muted>
                  <Button
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
          </>
        )}
      </ConnectionGate>
    </Page>
  );
}
