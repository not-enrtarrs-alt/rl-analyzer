"""Guarded delivery transitions mixed into the SQLite store."""

from datetime import datetime, timedelta, timezone
import math
import sqlite3
from typing import Any

from .stats import InvalidReplay, parse_replay_date
from .store_utils import StoreError, now_stamp, utc_stamp


def set_last_success(db: sqlite3.Connection, timestamp: str) -> None:
    """Update last success monotonically, even if the system clock shifts."""
    row = db.execute("SELECT value FROM meta WHERE key='last_success_at'").fetchone()
    if row:
        try:
            if parse_replay_date(row[0]) >= parse_replay_date(timestamp):
                return
        except InvalidReplay:
            raise StoreError("Stored last-success timestamp is invalid") from None
    db.execute("""INSERT INTO meta(key,value) VALUES ('last_success_at', ?)
                  ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (timestamp,))


class DeliveryStoreMixin:
    """State changes that surround an X posting attempt."""

    def latest_pending(self) -> dict[str, Any] | None:
        """Find the newest generated tweet, without changing its state."""
        row = self._connection.execute("""SELECT * FROM replays WHERE status='generated'
            ORDER BY match_date DESC, created_at DESC, replay_id DESC LIMIT 1""").fetchone()
        return dict(row) if row else None

    def latest_undelivered(self) -> dict[str, Any] | None:
        """Find cached text whose manual file delivery has not succeeded."""
        row = self._connection.execute("""SELECT * FROM replays WHERE status='generated' AND manual_delivered_at IS NULL
            ORDER BY match_date DESC, created_at DESC, replay_id DESC LIMIT 1""").fetchone()
        return dict(row) if row else None

    def posting_rows(self) -> list[dict[str, Any]]:
        """Return all in-flight/unknown posts for inspection."""
        rows = self._connection.execute("SELECT * FROM replays WHERE status='posting' ORDER BY updated_at DESC").fetchall()
        return [dict(row) for row in rows]

    def start_posting(self, replay_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        """Reserve a cached tweet; any existing posting row blocks live posts."""
        timestamp = now_stamp(now)
        with self._write() as db:
            if db.execute("SELECT 1 FROM replays WHERE status='posting' LIMIT 1").fetchone():
                raise StoreError("An in-flight or unknown post requires inspection")
            row = self.get_replay(replay_id)
            if not row or row["status"] != "generated" or not row["tweet_text"]:
                raise StoreError("No generated tweet is available for posting")
            db.execute("UPDATE replays SET status='posting', reason=NULL, updated_at=? WHERE replay_id=?",
                       (timestamp, replay_id))
            return self.get_replay(replay_id)

    def mark_post_failed(self, replay_id: str, *, outcome_known: bool,
                         now: datetime | None = None) -> dict[str, Any]:
        """Retry confirmed failures; preserve the guard if delivery is uncertain."""
        timestamp = now_stamp(now)
        with self._write() as db:
            row = self.get_replay(replay_id)
            if not row or row["status"] != "posting":
                raise StoreError("No in-flight post to update")
            if row["reason"] == "posting_unknown":
                raise StoreError("Unknown post outcome requires manual inspection")
            status, reason = ("generated", "post_failed") if outcome_known else ("posting", "posting_unknown")
            db.execute("UPDATE replays SET status=?, reason=?, updated_at=? WHERE replay_id=?",
                       (status, reason, timestamp, replay_id))
            return self.get_replay(replay_id)

    def mark_posted(self, replay_id: str, tweet_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        """Atomically record a confirmed live post and advance the cooldown."""
        if not isinstance(tweet_id, str) or not tweet_id.strip():
            raise StoreError("Confirmed tweet ID is required")
        timestamp = now_stamp(now)
        with self._write() as db:
            row = self.get_replay(replay_id)
            if row and row["status"] == "posted" and row["tweet_id"] == tweet_id:
                if db.execute("SELECT 1 FROM posts WHERE replay_id=? AND tweet_id=? AND text=?",
                              (replay_id, tweet_id, row["tweet_text"])).fetchone():
                    return row
                raise StoreError("Posted replay has no matching post record")
            if not row or row["status"] != "posting" or not row["tweet_text"]:
                raise StoreError("No in-flight post to confirm")
            try:
                db.execute("INSERT INTO posts(replay_id, tweet_id, text, posted_at) VALUES (?, ?, ?, ?)",
                           (replay_id, tweet_id, row["tweet_text"], timestamp))
            except sqlite3.IntegrityError:
                raise StoreError("Tweet ID is already recorded") from None
            db.execute("""UPDATE replays SET status='posted', tweet_id=?, posted_at=?, updated_at=?, reason=NULL
                          WHERE replay_id=?""", (tweet_id, timestamp, timestamp, replay_id))
            set_last_success(db, timestamp)
            return self.get_replay(replay_id)

    def skip_expired(self, replay_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        """Terminally skip an expired cached tweet without touching its text."""
        timestamp = now_stamp(now)
        with self._write() as db:
            row = self.get_replay(replay_id)
            if not row or row["status"] != "generated":
                raise StoreError("Only a generated tweet can expire before posting")
            db.execute("UPDATE replays SET status='skipped', reason='expired_before_post', updated_at=? WHERE replay_id=?",
                       (timestamp, replay_id))
            return self.get_replay(replay_id)

    def mark_manual_delivered(self, replay_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        """Record successful manual delivery without recording a live post."""
        timestamp = now_stamp(now)
        with self._write() as db:
            row = self.get_replay(replay_id)
            if not row or row["status"] != "generated" or not row["tweet_text"]:
                raise StoreError("No generated tweet is available for manual delivery")
            db.execute("UPDATE replays SET manual_delivered_at=?, updated_at=? WHERE replay_id=?",
                       (timestamp, timestamp, replay_id))
            set_last_success(db, timestamp)
            return self.get_replay(replay_id)

    def last_success_at(self) -> datetime | None:
        """Return the later of manual/live success metadata and live posts."""
        values = [row[0] for row in self._connection.execute("SELECT posted_at FROM posts")]
        meta = self._connection.execute("SELECT value FROM meta WHERE key='last_success_at'").fetchone()
        if meta:
            values.append(meta[0])
        try:
            dates = [parse_replay_date(value) for value in values]
        except InvalidReplay:
            raise StoreError("Stored success timestamp is invalid") from None
        return max(dates) if dates else None

    def in_cooldown(self, now: datetime, hours: float) -> bool:
        """Check cooldown from the latest success; force is handled by the caller."""
        utc_stamp(now)  # Reject naive timestamps instead of silently using local time.
        if (isinstance(hours, bool) or not isinstance(hours, (int, float))
                or (isinstance(hours, float) and not math.isfinite(hours)) or hours <= 0):
            raise StoreError("Cooldown hours must be positive")
        try:
            duration = timedelta(hours=hours)
        except OverflowError:
            raise StoreError("Cooldown hours are too large") from None
        last = self.last_success_at()
        return last is not None and now.astimezone(timezone.utc) - last < duration
