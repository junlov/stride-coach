import type { Schema } from "../src/api/client";
export const connection = {
  serverUrl: "https://coach.example.test",
  token: "synthetic-test-credential",
};
export const metrics: Schema<"Metrics"> = {
  week: 1,
  planned_sessions: 2,
  matched_sessions: 1,
  compliance: 0.5,
  planned_minutes: 60,
  completed_minutes: 30,
  trimp: 24,
  missing_hr: 1,
  matches: [],
};
export const workout: Schema<"WorkoutSummary"> = {
  id: "synthetic-run",
  name: "Easy Run 30 min",
  day: "2026-10-05",
  week: 1,
  phase: "base",
  kind: "easy",
  steps: [{ label: "Easy running", minutes: 30, hr_min: 120, hr_max: 140 }],
};
export const plan: Schema<"PlanView"> = {
  id: "synthetic-plan",
  setup: {
    start: "2026-10-05",
    race_date: "2026-12-06",
    days_per_week: 2,
    goal: "5k",
  },
  fitness: {
    vdot: null,
    easy_pace: null,
    weekly_minutes: 60,
    source: "synthetic baseline",
  },
  workouts: [workout],
  warnings: [],
};
export const status: Schema<"Status"> = {
  plan_id: plan.id,
  scheduled_workouts: 0,
  sync: null,
  weeks: [metrics],
  adjustments: [],
};
export const adjustment: Schema<"Adjustment"> = {
  inputs: { proposal_fingerprint: "reviewed-proposal" },
  week: 2,
  before_minutes: 60,
  after_minutes: 45,
  factor: 0.75,
  reasons: ["Reduce volume after missed sessions."],
  applied: false,
};
export const writes: Schema<"WriteResult">[] = [
  {
    action: "create",
    workout_id: workout.id,
    date: workout.day,
    ownership_tag: "stride-coach:synthetic",
  },
];
export function response(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response;
}
export function mockServer(overrides: Record<string, unknown> = {}) {
  const routes: Record<string, unknown> = {
    "/status": status,
    "/sync/status": {},
    "/sync/open": { skipped: true },
    "/garmin/status": {
      connected: true,
      display_name: "Synthetic Runner",
      expires_at: null,
    },
    "/plan": plan,
    "/weeks/1": { workouts: [{ workout, minutes: 30 }], metrics },
    "/load": [{ week: 1, completed_minutes: 30, trimp: 24, missing_hr: 1 }],
    "/compliance": [metrics],
    "/adjustments/propose/2": {
      adjustment,
      preview_only: true,
      requires_closed_week_and_sync: true,
    },
    "/adapt": { ...adjustment, applied: true },
    "/push": writes,
    "/remove": [{ action: "remove", remote_id: "synthetic-remote" }],
    "/sync": {
      synced: 1,
      since: "2026-09-07",
      until: "2026-10-05",
      source: "Garmin",
    },
    "/goal": {
      plan_id: plan.id,
      sessions: 2,
      fitness: plan.fitness,
      warnings: ["Conservative starting volume."],
    },
    ...overrides,
  };
  const fetcher = jest.fn(async (input: string | URL | Request) => {
    const path = new URL(String(input)).pathname;
    if (!(path in routes)) throw new Error(`Unexpected mock route ${path}`);
    return response(routes[path]);
  });
  global.fetch = fetcher as typeof fetch;
  return fetcher;
}
