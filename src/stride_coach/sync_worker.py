"""One local worker; PostgreSQL arbitrates all sync work across processes."""

import calendar
import logging
from datetime import UTC, date, datetime, time, timedelta
from threading import Event, Thread
from uuid import uuid4
from zoneinfo import ZoneInfo

from .garmin_auth import GarminError
from .service import Coach, SyncRequest
from .storage import Store
from .sync_models import HistoryRequest, SyncAttempt

logger = logging.getLogger(__name__)
PAGE_SIZE = 100


def history_start(choice: str, today: date) -> date:
    if choice == "12-weeks":
        return today - timedelta(weeks=12)
    if choice == "everything":
        return date(1970, 1, 1)
    month = today.year * 12 + today.month - 1 - 6
    year, month = divmod(month, 12)
    month += 1
    return date(year, month, min(today.day, calendar.monthrange(year, month)[1]))


class SyncWorker:
    def __init__(self, config, connection, client_factory):
        self.config = config
        self.connection = connection
        self.client_factory = client_factory
        self.stop = Event()
        self.thread = None

    def now(self):
        return datetime.now(ZoneInfo(self.config.timezone))

    def store(self):
        return Store(self.config.database_url.get_secret_value(), migrate=False)

    def connected(self):
        # Check stored credentials only. The adapter handles renewal and reconnect errors;
        # status() itself may contact Garmin and must not run before the sync claim.
        with self.connection.vault.locked():
            return bool(self.connection.vault.read().get("tokens"))

    def automatic(self, store, source, now):
        with store.try_lock() as acquired:
            status = store.sync_status()
            if not acquired:
                status.skipped = True
                return status
            last = store.latest_regular_sync()
            if last and last.result == "running":
                last.result = "error"
                last.error = (
                    "Sync interrupted. Retry from Actions or wait for the next automatic sync."
                )
                last.finished_at = now
                store.save_attempt(last)
            due = True
            if last:
                if source == "daily":
                    due = last.started_at.astimezone(now.tzinfo).date() < now.date()
                else:
                    due = (
                        now - last.started_at
                    ).total_seconds() >= self.config.sync_open_hours * 3600
            if not due or not self.connected():
                status = store.sync_status()
                status.skipped = True
                return status
            try:
                plan_start = store.plan().setup.start
            except ValueError:
                plan_start = now.date()
            try:
                Coach(store, self.config.tokens, self.client_factory).sync(
                    SyncRequest(since=min(plan_start - timedelta(days=28), now.date())),
                    today=now.date(),
                    source=source,
                    now=now,
                )
            except GarminError:
                pass  # Safe error and reconnect guidance are persisted by Coach.sync.
            return store.sync_status()

    def enqueue(self, store, request: HistoryRequest):
        with store.lock():
            old = store.sync_status().history
            if old and old.result == "running":
                return old
            if old and old.history_range == request.range:
                if old.result != "success":
                    old.result, old.error, old.finished_at = "running", None, None
                    store.save_attempt(old)
                return old
            if not self.connected():
                raise ValueError("Connect Garmin before importing past runs.")
            now = self.now()
            job = SyncAttempt(
                id=uuid4().hex,
                source="history",
                started_at=now,
                since=history_start(request.range, now.date()),
                until=now.date(),
                history_range=request.range,
            )
            store.save_attempt(job)
            return job

    def history_page(self, store):
        with store.try_lock() as acquired:
            if not acquired:
                return
            job = store.sync_status().history
            if not job or job.result != "running":
                return
            now = self.now()
            if job.next_page_at and now < job.next_page_at:
                return
            try:
                client = self.client_factory(self.config.tokens)
                rows = client.activity_page(job.since, job.until, job.next_page, PAGE_SIZE)
                runs = [a for a in rows if job.since <= a.day <= job.until]
                job.next_page_at = self.now() + timedelta(seconds=self.config.import_page_delay)
                job.next_page += len(rows)
                job.activity_count += len(runs)
                if len(rows) < PAGE_SIZE:
                    job.result, job.finished_at = "success", datetime.now(UTC)
                store.save_history_page(job, runs)
            except Exception:
                job = store.sync_status().history
                job.result, job.finished_at = "error", datetime.now(UTC)
                job.error = "Import paused. Check connectivity or reconnect Garmin, then resume."
                store.save_attempt(job)

    def tick(self):
        store = self.store()
        try:
            now = self.now()
            if self.config.sync_enabled and now.time() >= time.fromisoformat(self.config.sync_time):
                self.automatic(store, "daily", now)
            self.history_page(store)
        finally:
            store.close()

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:
                # Do not log upstream exceptions or credentials. Retry on the next tick.
                logger.warning("Sync worker could not complete its check.")
            self.stop.wait(max(1.0, self.config.import_page_delay))

    def start(self):
        if self.thread is None:
            self.thread = Thread(target=self.run, name="stride-sync", daemon=True)
            self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join()
