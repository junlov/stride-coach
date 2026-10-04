/** Loopback proof with a disposable database. Never connects to Garmin. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdir, mkdtemp, open } from "node:fs/promises";
import { createServer } from "node:net";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { createClient } from "../src/api/client";

async function main() {
  const root = fileURLToPath(new URL("../../", import.meta.url));
  const local = resolve(root, ".local");
  await mkdir(local, { recursive: true });
  const directory = await mkdtemp(resolve(local, "mobile-proof-"));
  const socket = createServer();
  await new Promise<void>((done) => socket.listen(0, "127.0.0.1", done));
  const address = socket.address();
  assert(address && typeof address !== "string");
  const port = address.port;
  await new Promise<void>((done, reject) =>
    socket.close((error) => (error ? reject(error) : done())),
  );
  const token = randomBytes(32).toString("hex");
  const serverUrl = `http://127.0.0.1:${port}`;
  const log = await open(resolve(directory, "server.log"), "w");
  const child = spawn(
    "uv",
    [
      "run",
      "python",
      "examples/proof_server.py",
      "--tokens",
      resolve(directory, "garmin"),
      "serve",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    {
      cwd: root,
      env: { ...process.env, STRIDE_COACH_API_TOKEN: token },
      stdio: ["ignore", log.fd, log.fd],
    },
  );
  const exited = new Promise<void>((done, reject) => {
    child.once("exit", () => done());
    child.once("error", reject);
  });
  try {
    let ready = false;
    for (let i = 0; i < 100; i++) {
      if (child.exitCode !== null)
        throw new Error(
          "Proof server exited early. Inspect the ignored local log.",
        );
      try {
        ready = (await fetch(`${serverUrl}/status`)).status === 401;
      } catch {
        /* Wait for loopback startup. */
      }
      if (ready) break;
      await delay(100);
    }
    assert(ready, "Proof server must start");
    const client = createClient({ serverUrl, token });
    await assert.rejects(
      createClient({ serverUrl, token: "invalid" }).status(),
      /Authentication failed/,
    );
    console.log("auth: invalid bearer rejected");
    const monday = new Date();
    monday.setUTCDate(monday.getUTCDate() + ((8 - monday.getUTCDay()) % 7));
    const end = new Date(monday);
    end.setUTCDate(end.getUTCDate() + 84);
    const created = await client.goal({
      setup: {
        goal: "return-to-running",
        start: monday.toISOString().slice(0, 10),
        race_date: end.toISOString().slice(0, 10),
        days_per_week: 3,
      },
    });
    assert(created.sessions > 0);
    const [plan, week, load, compliance] = await Promise.all([
      client.plan(),
      client.week(1),
      client.load(),
      client.compliance(),
    ]);
    assert(
      plan.id === created.plan_id &&
        week.workouts.length > 0 &&
        load.length === compliance.length,
    );
    console.log(
      `plan: ${created.sessions} synthetic sessions; week, load, compliance read successfully`,
    );
    const synced = await client.sync({ activities: [] });
    assert.equal(synced.synced, 0);
    const proposal = await client.propose(2);
    assert.equal(proposal.preview_only, true);
    const preview = await client.push({ week: 1, dry_run: true, apply: false });
    assert(
      preview.length > 0 && preview.every((item) => item.action === "preview"),
    );
    const removal = await client.remove({ dry_run: true, apply: false });
    assert.equal(removal.length, plan.workouts.length);
    assert(
      removal.every(
        (item) => item.action === "preview removal" && item.ownership_tag,
      ),
    );
    assert.equal((await client.status()).scheduled_workouts, 0);
    console.log(
      "actions: local empty sync, adjustment proposal, push/removal previews; zero Garmin calls",
    );
    console.log(
      "proof: mobile TypeScript client completed real FastAPI loopback workflow",
    );
  } finally {
    child.kill("SIGTERM");
    const timeout = setTimeout(() => child.kill("SIGKILL"), 5000);
    await exited.finally(() => {
      clearTimeout(timeout);
    });
    await log.close();
  }
}
main().catch(() => {
  console.error(
    "Mobile loopback proof failed. Inspect .local/mobile-proof-*/server.log.",
  );
  process.exitCode = 1;
});
