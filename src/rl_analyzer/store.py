"""SQLite persistence for replay deduplication and delivery state."""

from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Sequence

from .select import match_key as canonical_match_key
from .stats import InvalidReplay, parse_replay_date
from .store_delivery import DeliveryStoreMixin
from .store_identity import identity_where
from .store_schema import SCHEMA_VERSION, initialize, schema_version
from .store_utils import StoreError, now_stamp, utc_stamp

_CONSUMED = "(status <> 'analysis_failed' OR attempts >= 2 OR reason = 'analysis_in_progress')"


def _match_details(match: dict[str, Any] | None) -> tuple[str | None, int | None, int | None]:
    if match is None:
        return None, None, None
    if not isinstance(match, dict) or not isinstance(match.get("score"), dict):
        raise StoreError("Match result and score are invalid")
    result, score = match.get("result"), match["score"]
    trio, opponents = score.get("trio"), score.get("opponents")
    if (isinstance(trio, bool) or not isinstance(trio, int) or trio < 0
            or isinstance(opponents, bool) or not isinstance(opponents, int) or opponents < 0):
        raise StoreError("Match result and score are invalid")
    expected = "win" if trio > opponents else "loss" if trio < opponents else "draw"
    if result != expected:
        raise StoreError("Match result and score are inconsistent")
    return result, trio, opponents


class Store(DeliveryStoreMixin):
    """Manage a SQLite database; read-only mode does not create or change it."""

    def __init__(self, path: Path, *, readonly: bool = False) -> None:
        path = Path(path)
        self.readonly = readonly
        if readonly:
            if not path.is_file():
                raise StoreError("Database does not exist")
            self._connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(path)
        self._connection.row_factory = sqlite3.Row
        try:
            if readonly:
                if schema_version(self._connection) != SCHEMA_VERSION:
                    raise StoreError("Unsupported or missing database schema version")
            else:
                initialize(self._connection)
        except ValueError:
            self._connection.close()
            raise StoreError("Unsupported database schema version") from None
        except Exception:
            self._connection.close()
            raise

    def close(self) -> None:
        """Close the underlying connection."""
        self._connection.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        if self.readonly:
            raise StoreError("Database is read-only")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield self._connection
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def get_replay(self, replay_id: str) -> dict[str, Any] | None:
        """Return a replay row or None."""
        row = self._connection.execute("SELECT * FROM replays WHERE replay_id = ?", (replay_id,)).fetchone()
        return dict(row) if row else None

    def inflight_analyses(self) -> list[dict[str, Any]]:
        """Return guarded analysis reservations that may require inspection."""
        rows = self._connection.execute("""SELECT * FROM replays WHERE status='analysis_failed'
            AND reason='analysis_in_progress' ORDER BY updated_at DESC""").fetchall()
        return [dict(row) for row in rows]

    def recent_replays(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent replay records without modifying the database."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise StoreError("History limit must be positive")
        rows = self._connection.execute("""SELECT * FROM replays
            ORDER BY match_date DESC, created_at DESC, replay_id DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def replay_is_consumed(self, replay_id: str) -> bool:
        """Treat successful, terminal and in-flight rows as consumed."""
        row = self._connection.execute(
            f"SELECT 1 FROM replays WHERE replay_id = ? AND {_CONSUMED} LIMIT 1", (replay_id,)
        ).fetchone()
        return row is not None

    def match_is_consumed(self, match_key: str, *, exclude_replay_id: str,
                          match_guid: str | None = None, rocket_league_id: str | None = None) -> bool:
        """Check for a different consumed upload of the same match."""
        where, values = identity_where(match_key, match_guid, rocket_league_id)
        row = self._connection.execute(
            f"SELECT 1 FROM replays WHERE {where} AND replay_id <> ? AND {_CONSUMED} LIMIT 1",
            (*values, exclude_replay_id),
        ).fetchone()
        return row is not None

    def record_duplicate(self, replay: dict[str, Any], match_key: str, *, now: datetime | None = None) -> None:
        """Idempotently record a consumed match's other upload as skipped."""
        replay_id = replay.get("id")
        if not isinstance(replay_id, str) or not replay_id.strip() or not isinstance(match_key, str) or not match_key.strip():
            raise StoreError("Replay ID and match key are required")
        try:
            match_date = utc_stamp(parse_replay_date(replay.get("date")))
        except InvalidReplay:
            raise StoreError("Replay date is missing or invalid") from None
        timestamp = now_stamp(now)
        guid = replay.get("match_guid") if isinstance(replay.get("match_guid"), str) else None
        rocket_id = replay.get("rocket_league_id") if isinstance(replay.get("rocket_league_id"), str) else None
        where, values = identity_where(match_key, guid, rocket_id)
        with self._write() as db:
            if not self.match_is_consumed(match_key, exclude_replay_id=replay_id, match_guid=guid, rocket_league_id=rocket_id):
                raise StoreError("Cannot mark a match duplicate without a consumed original")
            terminal = db.execute(
                f"""SELECT 1 FROM replays WHERE {where} AND replay_id <> ? AND {_CONSUMED}
                    AND NOT (status = 'analysis_failed' AND COALESCE(reason, '') = 'analysis_in_progress') LIMIT 1""",
                (*values, replay_id),
            ).fetchone()
            if not terminal:
                # An in-flight analysis can fail and be retried; do not prematurely
                # make its other uploads terminal duplicates.
                return
            existing = self.get_replay(replay_id)
            if existing:
                if not db.execute(f"SELECT 1 FROM replays WHERE replay_id = ? AND {where}", (replay_id, *values)).fetchone():
                    raise StoreError("Replay ID is already associated with a different match")
                if existing["status"] == "analysis_failed" and existing["reason"] != "analysis_in_progress":
                    db.execute("UPDATE replays SET status='skipped', reason='duplicate_match', updated_at=? WHERE replay_id=?",
                               (timestamp, replay_id))
                return
            db.execute("""INSERT INTO replays
                (replay_id, match_key, match_guid, rocket_league_id, match_date, status, reason, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'skipped', 'duplicate_match', ?, ?)""",
                (replay_id, match_key, guid, rocket_id, match_date, timestamp, timestamp))

    def reserve_analysis(self, replay: dict[str, Any], *, provider: str | None = None,
                         model: str | None = None, match: dict[str, Any] | None = None,
                         names: Sequence[str] | None = None,
                         now: datetime | None = None) -> dict[str, Any]:
        """Atomically reserve one attempt; use the returned replay ID for updates.

        An upload of an already-failed match reuses the original row and attempt
        count. A reservation left by a crash remains blocked for inspection.
        """
        replay_id = replay.get("id")
        if not isinstance(replay_id, str) or not replay_id.strip() or replay_id != replay_id.strip():
            raise StoreError("Replay ID is required")
        try:
            key = canonical_match_key(replay)
            match_date = utc_stamp(parse_replay_date(replay.get("date")))
        except InvalidReplay:
            raise StoreError("Replay identity or date is invalid") from None
        timestamp = now_stamp(now)
        result, trio_goals, opponent_goals = _match_details(match)
        if names is not None and (not names or any(not isinstance(name, str) or not name.strip() for name in names)):
            raise StoreError("Player names are invalid")
        player_names = json.dumps(list(names), ensure_ascii=False) if names is not None else None
        guid = replay.get("match_guid") if isinstance(replay.get("match_guid"), str) else None
        rocket_id = replay.get("rocket_league_id") if isinstance(replay.get("rocket_league_id"), str) else None
        guid = guid.strip() if guid and guid.strip() else None
        rocket_id = rocket_id.strip() if rocket_id and rocket_id.strip() else None
        where, values = identity_where(key, guid, rocket_id)
        with self._write() as db:
            existing = self.get_replay(replay_id)
            if existing and existing["match_key"].casefold() != key.casefold():
                raise StoreError("Replay ID is already associated with a different match")
            rows = db.execute(f"SELECT * FROM replays WHERE {where} ORDER BY created_at, replay_id", values).fetchall()
            if db.execute(f"SELECT 1 FROM replays WHERE {where} AND {_CONSUMED} LIMIT 1", values).fetchone():
                raise StoreError("Match is already consumed or analysis is in progress")
            if len(rows) > 1:
                raise StoreError("Multiple retryable rows for one match require inspection")
            if rows:
                owner = rows[0]
                if owner["attempts"] != 1:
                    raise StoreError("Invalid analysis attempt count requires inspection")
                for name, value in (("match_guid", guid), ("rocket_league_id", rocket_id)):
                    if value and owner[name] and value.casefold() != owner[name].strip().casefold():
                        raise StoreError("Conflicting match identifiers require inspection")
                for name, value in (("result", result), ("trio_goals", trio_goals), ("opponent_goals", opponent_goals)):
                    if value is not None and owner[name] is not None and owner[name] != value:
                        raise StoreError("Retry match result or score conflicts with the stored match")
                replay_id = owner["replay_id"]
                db.execute("""UPDATE replays SET attempts=attempts+1, reason='analysis_in_progress',
                    provider=?, model=?, result=COALESCE(result, ?), trio_goals=COALESCE(trio_goals, ?),
                    opponent_goals=COALESCE(opponent_goals, ?), player_names=COALESCE(?, player_names),
                    match_guid=COALESCE(match_guid, ?), rocket_league_id=COALESCE(rocket_league_id, ?),
                    updated_at=? WHERE replay_id=?""",
                    (provider, model, result, trio_goals, opponent_goals, player_names, guid, rocket_id, timestamp, replay_id))
            else:
                db.execute("""INSERT INTO replays (replay_id, match_key, match_guid, rocket_league_id,
                    match_date, result, trio_goals, opponent_goals, player_names, status, reason, attempts, provider, model, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'analysis_failed', 'analysis_in_progress', 1, ?, ?, ?, ?)""",
                    (replay_id, key, guid, rocket_id, match_date, result, trio_goals, opponent_goals, player_names, provider, model, timestamp, timestamp))
            return self.get_replay(replay_id)

    def mark_analysis_failed(self, replay_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        """Finish a reserved failure; the second failure is terminal."""
        timestamp = now_stamp(now)
        with self._write() as db:
            row = self.get_replay(replay_id)
            if not row or row["status"] != "analysis_failed" or row["reason"] != "analysis_in_progress":
                raise StoreError("No reserved analysis attempt")
            status = "skipped" if row["attempts"] >= 2 else "analysis_failed"
            db.execute("UPDATE replays SET status=?, reason='ai_failed', updated_at=? WHERE replay_id=?",
                       (status, timestamp, replay_id))
            return self.get_replay(replay_id)

    def save_generated(self, replay_id: str, text: str, *, now: datetime | None = None) -> dict[str, Any]:
        """Persist an already-validated tweet before any delivery is attempted."""
        if not isinstance(text, str) or not text.strip():
            raise StoreError("Generated tweet text is required")
        timestamp = now_stamp(now)
        with self._write() as db:
            row = self.get_replay(replay_id)
            if not row or row["status"] != "analysis_failed" or row["reason"] != "analysis_in_progress":
                raise StoreError("No reserved analysis attempt")
            if self.match_is_consumed(row["match_key"], exclude_replay_id=replay_id,
                                      match_guid=row["match_guid"], rocket_league_id=row["rocket_league_id"]):
                raise StoreError("Match is already consumed")
            db.execute("""UPDATE replays SET status='generated', tweet_text=?, reason=NULL, updated_at=?
                          WHERE replay_id=?""", (text, timestamp, replay_id))
            return self.get_replay(replay_id)
