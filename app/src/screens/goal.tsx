import { useRef, useState } from "react";
import { Schema } from "../api/client";
import {
  Button,
  Card,
  ConnectionGate,
  Copy,
  ErrorMessage,
  Field,
  Heading,
  Muted,
  Page,
} from "../components/ui";
import { validDate } from "../dates";
import { useConnection } from "../state/connection";
const goals: Schema<"Goal">[] = [
  "5k",
  "10k",
  "half",
  "marathon",
  "return-to-running",
];
export default function GoalScreen() {
  const { client, refresh } = useConnection();
  const [goal, setGoal] = useState<Schema<"Goal">>("5k");
  const [start, setStart] = useState("");
  const [race, setRace] = useState("");
  const [days, setDays] = useState("3");
  const [longDay, setLongDay] = useState("6");
  const [resting, setResting] = useState("60");
  const [max, setMax] = useState("190");
  const [review, setReview] = useState<Schema<"Setup"> | null>(null);
  const [result, setResult] = useState<Schema<"Created"> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  function prepare() {
    setError(null);
    setResult(null);
    const duration = (Date.parse(race) - Date.parse(start)) / 86400000;
    if (
      !validDate(start) ||
      !validDate(race) ||
      new Date(`${start}T00:00:00Z`).getUTCDay() !== 1 ||
      duration < 55 ||
      duration > 365
    ) {
      setError(
        "Use valid YYYY-MM-DD dates. Start on a Monday, with completion 8 to 52 weeks later.",
      );
      return;
    }
    if (
      ![days, longDay, resting, max].every((v) => /^\d+$/.test(v)) ||
      +days < 2 ||
      +days > (goal === "return-to-running" ? 3 : 6) ||
      +longDay > 6 ||
      +resting < 30 ||
      +resting > 120 ||
      +max < 100 ||
      +max > 240 ||
      +max <= +resting
    ) {
      setError(
        "Check your training days (2 to 6, or 2 to 3 for return to running), long-run day (0 to 6), and heart rates (resting 30 to 120, maximum 100 to 240 and above resting).",
      );
      return;
    }
    setReview({
      goal,
      start,
      race_date: race,
      days_per_week: +days,
      long_run_day: +longDay,
      athlete: { resting_hr: +resting, max_hr: +max },
    });
  }
  async function submit() {
    if (!client || !review || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      setResult(await client.goal({ setup: review }));
      setReview(null);
      refresh();
    } catch (e) {
      setError((e as Error).message);
      setReview(null);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <Page title="Choose your goal">
      <ConnectionGate>
        {review ? (
          <Card>
            <Heading>Review your goal</Heading>
            <Copy>
              {review.goal} · {review.days_per_week} days per week
            </Copy>
            <Copy>
              {review.start} to {review.race_date}
            </Copy>
            <Muted>
              This creates a new plan using activities already stored on your
              server. The server supports one plan per database and refuses to
              replace an existing plan. To start again, configure a fresh
              database on your server.
            </Muted>
            <Button
              label="Confirm new plan"
              onPress={() => void submit()}
              disabled={busy}
            />
            <Button
              label="Back to editing"
              onPress={() => setReview(null)}
              disabled={busy}
            />
          </Card>
        ) : (
          <Card>
            <Heading>Distance</Heading>
            {goals.map((item) => (
              <Button
                key={item}
                label={`${goal === item ? "Selected: " : ""}${item}`}
                onPress={() => setGoal(item)}
                disabled={busy}
              />
            ))}
            <Field
              label="Start Monday (YYYY-MM-DD)"
              value={start}
              onChangeText={setStart}
              editable={!busy}
            />
            <Field
              label="Race or completion date (YYYY-MM-DD)"
              value={race}
              onChangeText={setRace}
              editable={!busy}
            />
            <Field
              label="Days per week"
              value={days}
              onChangeText={setDays}
              keyboardType="number-pad"
              editable={!busy}
            />
            <Field
              label="Long-run day (0 Monday, 6 Sunday)"
              value={longDay}
              onChangeText={setLongDay}
              keyboardType="number-pad"
              editable={!busy}
            />
            <Field
              label="Resting heart rate"
              value={resting}
              onChangeText={setResting}
              keyboardType="number-pad"
              editable={!busy}
            />
            <Field
              label="Maximum heart rate"
              value={max}
              onChangeText={setMax}
              keyboardType="number-pad"
              editable={!busy}
            />
            <Button label="Review goal" onPress={prepare} disabled={busy} />
          </Card>
        )}
        <ErrorMessage message={error} />
        {result && (
          <Card>
            <Heading>Plan created</Heading>
            <Copy>
              {result.sessions} sessions · {result.fitness.source}
            </Copy>
            {result.warnings.map((warning) => (
              <Muted key={warning}>{warning}</Muted>
            ))}
          </Card>
        )}
      </ConnectionGate>
    </Page>
  );
}
