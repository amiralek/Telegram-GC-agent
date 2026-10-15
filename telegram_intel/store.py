"""SQLite snapshots, coverage and restart-safe AI checkpoints."""

from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from .models import Group, Message, UTC, micros
from .security import IntelError, protect


class Store:
    def __init__(self, path: Path, *, secure: bool = True):
        self.path = path
        if path.is_symlink():
            raise IntelError("Cache file must not be a symbolic link.")
        if not path.exists():
            path.touch(mode=0o600)
        if secure:
            protect(path)
        self.db = sqlite3.connect(path, timeout=20)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=DELETE;
            PRAGMA secure_delete=ON;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS aliases (
                alias TEXT PRIMARY KEY COLLATE NOCASE, group_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                group_id INTEGER NOT NULL, id INTEGER NOT NULL, date_us INTEGER NOT NULL,
                payload TEXT NOT NULL, PRIMARY KEY(group_id,id));
            CREATE INDEX IF NOT EXISTS messages_date ON messages(group_id,date_us,id);
            CREATE TABLE IF NOT EXISTS coverage (
                group_id INTEGER NOT NULL, start_us INTEGER NOT NULL,
                end_us INTEGER NOT NULL, fetched_us INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS coverage_group ON coverage(group_id,start_us,end_us);
            CREATE TABLE IF NOT EXISTS checkpoints (
                key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY, created TEXT NOT NULL, payload TEXT NOT NULL);
        """)
        self.db.commit()

    def close(self):
        self.db.close()

    def save_groups(self, groups: Iterable[Group]):
        with self.db:
            self.db.execute("DELETE FROM groups")
            self.db.executemany("INSERT INTO groups VALUES (?,?)",
                                [(g.id, json.dumps(g.to_dict(), ensure_ascii=False)) for g in groups])

    def groups(self) -> list[Group]:
        return [Group(**json.loads(row[0])) for row in self.db.execute("SELECT payload FROM groups ORDER BY id")]

    def set_alias(self, alias: str, group_id: int):
        if not alias.strip() or len(alias) > 100:
            raise IntelError("Alias must contain 1-100 characters.")
        with self.db:
            old = self.db.execute("SELECT group_id FROM aliases WHERE alias=?", (alias,)).fetchone()
            if old and old[0] != group_id:
                raise IntelError("Alias already refers to another group. Choose a different alias.")
            self.db.execute("INSERT OR REPLACE INTO aliases VALUES (?,?)", (alias.strip(), group_id))

    def aliases(self) -> dict[str, int]:
        return {row[0].casefold(): row[1] for row in self.db.execute("SELECT alias,group_id FROM aliases")}

    def upsert(self, message: Message):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO messages VALUES (?,?,?,?)",
                            (message.group_id, message.id, micros(datetime.fromisoformat(message.date)),
                             json.dumps(message.to_dict(), ensure_ascii=False)))

    def query(self, group_id: int, start: datetime, end: datetime) -> list[Message]:
        return [Message.from_dict(json.loads(row[0])) for row in self.db.execute(
            "SELECT payload FROM messages WHERE group_id=? AND date_us>=? AND date_us<? ORDER BY date_us,id",
            (group_id, micros(start), micros(end)))]

    def message(self, group_id: int, message_id: int) -> Message | None:
        row = self.db.execute("SELECT payload FROM messages WHERE group_id=? AND id=?", (group_id, message_id)).fetchone()
        return Message.from_dict(json.loads(row[0])) if row else None

    def reconcile(self, group_id: int, start: datetime, end: datetime, seen: set[int]):
        # Only remove absent records after a successful full history traversal.
        with self.db:
            rows = self.db.execute("SELECT id FROM messages WHERE group_id=? AND date_us>=? AND date_us<?",
                                   (group_id, micros(start), micros(end))).fetchall()
            self.db.executemany("DELETE FROM messages WHERE group_id=? AND id=?",
                                [(group_id, row[0]) for row in rows if row[0] not in seen])

    def remove_message(self, group_id: int, message_id: int):
        with self.db:
            self.db.execute("DELETE FROM messages WHERE group_id=? AND id=?", (group_id, message_id))
            # A missing record invalidates coverage so later reads recheck history.
            self.db.execute("DELETE FROM coverage WHERE group_id=?", (group_id,))

    def complete(self, group_id: int, start: datetime, end: datetime, now: datetime | None = None):
        with self.db:
            self.db.execute("INSERT INTO coverage VALUES (?,?,?,?)",
                            (group_id, micros(start), micros(end), micros(now or datetime.now(UTC))))
            self.db.execute("DELETE FROM coverage WHERE fetched_us<?", (micros(datetime.now(UTC) - timedelta(days=30)),))

    def invalidate(self, group_id: int, start: datetime, end: datetime):
        # Existing overlapping windows are invalid after an interrupted refresh.
        # Discarding whole intervals may cause an extra read, never a false complete.
        with self.db:
            self.db.execute("DELETE FROM coverage WHERE group_id=? AND end_us>? AND start_us<?",
                            (group_id, micros(start), micros(end)))

    def missing(self, group_id: int, start: datetime, end: datetime, ttl: int,
                now: datetime | None = None) -> list[tuple[datetime, datetime]]:
        low, high = micros(start), micros(end)
        cutoff = micros((now or datetime.now(UTC)) - timedelta(seconds=ttl))
        spans = self.db.execute("""SELECT start_us,end_us FROM coverage WHERE group_id=?
            AND fetched_us>=? AND end_us>? AND start_us<? ORDER BY start_us,end_us""",
            (group_id, cutoff, low, high)).fetchall() if ttl else []
        gaps = []
        cursor = low
        for a, b in spans:
            a, b = max(low, a), min(high, b)
            if a > cursor:
                gaps.append((cursor, a))
            cursor = max(cursor, b)
        if cursor < high:
            gaps.append((cursor, high))
        return [(datetime.fromtimestamp(a / 1e6, UTC), datetime.fromtimestamp(b / 1e6, UTC)) for a, b in gaps]

    def checkpoint(self, key: str) -> dict | None:
        row = self.db.execute("SELECT payload FROM checkpoints WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_checkpoint(self, key: str, payload: dict):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO checkpoints VALUES (?,?)", (key, json.dumps(payload, ensure_ascii=False)))

    def save_report(self, report: dict):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO reports VALUES (?,?,?)",
                            (report["report_id"], report["created_at"], json.dumps(report, ensure_ascii=False)))

    def report(self, report_id: str) -> dict:
        row = self.db.execute("SELECT payload FROM reports WHERE id=?", (report_id,)).fetchone()
        if not row:
            raise IntelError("Report ID not found in the local cache.")
        return json.loads(row[0])

    def purge(self):
        with self.db:
            for table in ("messages", "coverage", "checkpoints", "reports", "groups", "aliases"):
                self.db.execute(f"DELETE FROM {table}")  # internal constant table names
        self.db.execute("VACUUM")
