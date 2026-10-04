import { useRef, useState } from "react";
import { Schema } from "../api/client";
import {
  Button,
  Card,
  Choice,
  Copy,
  ErrorMessage,
  Field,
  Heading,
  Muted,
  Page,
} from "../components/setup-ui";
import { ConnectionGate } from "../components/ui";
import { Link } from "expo-router";
import { validDate } from "../dates";
import { useConnection } from "../state/connection";
import { useTheme } from "../setup-theme";
const goals: Schema<"Goal">[] = [
  "5k",
  "10k",
  "half",
  "marathon",
  "return-to-running",
];
const goalNames = {
  "5k": "5K",
  "10k": "10K",
  half: "Half marathon",
  marathon: "Marathon",
  "return-to-running": "Return to running",
};
const weekdays = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];
export default function GoalScreen({
  onComplete,
}: { onComplete?: () => void } = {}) {
  const { client, refresh } = useConnection();
  const c = useTheme();
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
    <Page
      eyebrow={review ? "Initial plan · 2 of 2" : "Initial plan · 1 of 2"}
      title={
        result
          ? "Your plan is ready."
          : review
            ? "A plan that fits your week."
            : "Choose your rhythm."
      }
    >
      <ConnectionGate>
        {result ? (
          <Card>
            <Heading>Plan created</Heading>
            <Copy>
              {result.sessions} sessions · {result.fitness.source}
            </Copy>
            {result.warnings.map((warning) => (
              <Muted key={warning}>{warning}</Muted>
            ))}
            {onComplete ? (
              <Button label="Go to Today" onPress={onComplete} />
            ) : (
              <Link
                href="/"
                style={{ color: c.accent, fontSize: 16, paddingVertical: 14 }}
              >
                Go to Today
              </Link>
            )}
          </Card>
        ) : review ? (
          <Card>
            <Heading>Review your goal</Heading>
            <Copy>
              {goalNames[review.goal]} · {review.days_per_week} days per week
            </Copy>
            <Copy>
              {review.start} to {review.race_date}
            </Copy>
            <Copy>Long run: {weekdays[review.long_run_day ?? 6]}</Copy>
            <Copy>
              Resting / maximum heart rate: {review.athlete?.resting_hr} /{" "}
              {review.athlete?.max_hr} bpm
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
              variant="secondary"
              label="Back to editing"
              onPress={() => setReview(null)}
              disabled={busy}
            />
          </Card>
        ) : (
          <Card>
            <Choice
              label="Goal"
              value={goal}
              options={goals}
              names={goalNames}
              onChange={(next) => {
                setGoal(next);
                if (next === "return-to-running" && +days > 3) setDays("3");
              }}
              disabled={busy}
            />
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
            <Muted>
              Choose 8 to 52 weeks after the start. Run 2 to 6 days per week, or
              2 to 3 for return to running.
            </Muted>
            <Choice
              label="Days per week"
              value={days}
              options={
                goal === "return-to-running"
                  ? ["2", "3"]
                  : ["2", "3", "4", "5", "6"]
              }
              names={{
                "2": "2 days",
                "3": "3 days",
                "4": "4 days",
                "5": "5 days",
                "6": "6 days",
              }}
              onChange={setDays}
              disabled={busy}
            />
            <Choice
              label="Long-run day"
              value={longDay}
              options={weekdays.map((_, i) => String(i))}
              names={Object.fromEntries(
                weekdays.map((day, i) => [String(i), day]),
              )}
              onChange={setLongDay}
              disabled={busy}
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
            <Muted>
              Starting fitness comes from stored history on your server. Review
              the heart rates for your own fitness before continuing.
            </Muted>
            <Button label="Review goal" onPress={prepare} disabled={busy} />
          </Card>
        )}
        <ErrorMessage message={error} />
      </ConnectionGate>
    </Page>
  );
}
