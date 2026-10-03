"""Local SQLite records and a process lock for remote write reconciliation."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .models import Activity, Adjustment, Plan


class Store:
    def __init__(self, path: Path, read_only: bool = False):
        path = path.expanduser()
        self.path = path
        if read_only:
            self.db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            self.db.row_factory = sqlite3.Row
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS plan (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT);
            CREATE TABLE IF NOT EXISTS activities (id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS matches
                (workout_id TEXT PRIMARY KEY, activity_id TEXT UNIQUE NOT NULL, method TEXT);
            CREATE TABLE IF NOT EXISTS scheduled
                (workout_id TEXT PRIMARY KEY, remote_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                 scheduled INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS adjustments (week INTEGER PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        path.chmod(0o600)

    def close(self):
        self.db.close()

    @contextmanager
    def lock(self):
        # flock is released on process exit, including failures during a Garmin write.
        import fcntl

        with self.path.with_suffix(".lock").open("w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def plan(self) -> Plan:
        row = self.db.execute("SELECT data FROM plan WHERE id=1").fetchone()
        if not row:
            raise ValueError("No plan. Run stride-coach init first.")
        return Plan.model_validate_json(row[0])

    def initialize(self, plan: Plan):
        with self.db:
            if self.db.execute("SELECT 1 FROM plan").fetchone():
                raise ValueError("A plan already exists. Use a different --db for a new plan.")
            self.db.execute("INSERT INTO plan VALUES (1, ?)", (plan.model_dump_json(),))

    def activities(self) -> list[Activity]:
        return [
            Activity.model_validate_json(r[0])
            for r in self.db.execute("SELECT data FROM activities ORDER BY id")
        ]

    def save_sync(self, activities: list[Activity], since: str, until: str):
        with self.db:
            self.db.executemany(
                "INSERT OR REPLACE INTO activities VALUES (?, ?)",
                [(a.id, a.model_dump_json()) for a in activities],
            )
            self.db.execute(
                "INSERT OR REPLACE INTO metadata VALUES ('sync', ?)",
                (json.dumps({"since": since, "until": until}),),
            )

    def sync_window(self) -> dict:
        row = self.db.execute("SELECT value FROM metadata WHERE key='sync'").fetchone()
        return json.loads(row[0]) if row else {}

    def save_matches(self, matches: list[dict]):
        with self.db:
            self.db.execute("DELETE FROM matches")
            self.db.executemany(
                "INSERT INTO matches VALUES (?, ?, ?)",
                [(m["workout_id"], m["activity_id"], m["method"]) for m in matches],
            )

    def scheduled(self, workout_id: str):
        return self.db.execute(
            "SELECT * FROM scheduled WHERE workout_id=?", (workout_id,)
        ).fetchone()

    def save_remote(self, workout_id: str, remote_id: str, fingerprint: str, scheduled: bool):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO scheduled VALUES (?, ?, ?, ?)",
                (workout_id, remote_id, fingerprint, int(scheduled)),
            )

    def forget_remote(self, workout_id: str):
        with self.db:
            self.db.execute("DELETE FROM scheduled WHERE workout_id=?", (workout_id,))

    def adjustment(self, week: int) -> Adjustment | None:
        row = self.db.execute("SELECT data FROM adjustments WHERE week=?", (week,)).fetchone()
        return Adjustment.model_validate_json(row[0]) if row else None

    def apply(self, plan: Plan, adjustment: Adjustment):
        with self.db:
            if self.adjustment(adjustment.week):
                raise ValueError("This week was already adapted; repeated reductions are blocked.")
            adjustment.applied = True
            self.db.execute("UPDATE plan SET data=? WHERE id=1", (plan.model_dump_json(),))
            self.db.execute(
                "INSERT INTO adjustments VALUES (?, ?)",
                (adjustment.week, adjustment.model_dump_json()),
            )
