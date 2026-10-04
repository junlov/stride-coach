import { Card, Copy, Heading, Muted, NavLink } from "./ui";

export function EmptyPlan() {
  return (
    <Card>
      <Heading>Start with a destination.</Heading>
      <Copy>
        No active plan yet. Choose a goal and a schedule that fits your life.
      </Copy>
      <Muted>
        Your server derives your starting fitness from stored activity history.
        One active plan per database is supported.
      </Muted>
      <NavLink href="/goal" label="Set a running goal" primary />
    </Card>
  );
}
