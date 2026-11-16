"""SQLite store tests use isolated temporary databases."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest

from rl_analyzer.store import Store, StoreError
from rl_analyzer.store_schema import STATEMENTS

NOW = datetime(2026, 10, 30, 19, tzinfo=timezone.utc)


def seed(store, replay_id, match_key, status, attempts=0, reason=None):
    with store._connection:
        store._connection.execute("""INSERT INTO replays
            (replay_id, match_key, match_date, status, attempts, reason, created_at, updated_at)
            VALUES (?, ?, '2026-10-30T18:00:00.000000Z', ?, ?, ?,
                    '2026-10-30T19:00:00.000000Z', '2026-10-30T19:00:00.000000Z')""",
            (replay_id, match_key, status, attempts, reason))


def test_schema_idempotent_and_versioned(tmp_path):
    path = tmp_path / "nested" / "test.sqlite3"
    with Store(path):
        pass
    with Store(path):
        pass
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() == ("1",)
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"replays", "posts", "meta"} <= tables
        indexes = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert {"idx_replays_match_key", "idx_replays_status", "idx_replays_match_date", "idx_posts_tweet_id_unique"} <= indexes


def test_read_only_does_not_create_or_modify(tmp_path):
    path = tmp_path / "test.sqlite3"
    with pytest.raises(StoreError, match="does not exist"):
        Store(path, readonly=True)
    assert not path.exists()
    with Store(path):
        pass
    before = path.read_bytes()
    with Store(path, readonly=True) as store:
        assert store._connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == "1"
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            store._connection.execute("INSERT INTO meta VALUES ('x', 'y')")
    assert path.read_bytes() == before


def test_unknown_schema_is_not_modified(tmp_path):
    path = tmp_path / "test.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO meta VALUES ('schema_version', '999')")
    before = path.read_bytes()
    with pytest.raises(StoreError, match="Unsupported database schema"):
        Store(path)
    assert path.read_bytes() == before
    with pytest.raises(StoreError, match="schema version"):
        Store(path, readonly=True)


def test_existing_version_one_database_gains_nullable_history_columns(tmp_path):
    path = tmp_path / "old.sqlite3"
    original_schema = STATEMENTS[0]
    for column, kind in (("result", "TEXT"), ("trio_goals", "INTEGER"), ("opponent_goals", "INTEGER"), ("player_names", "TEXT"), ("manual_delivered_at", "TEXT")):
        original_schema = original_schema.replace(f"        {column} {kind},\n", "")
    with sqlite3.connect(path) as db:
        db.execute(original_schema)
        db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO meta VALUES ('schema_version', '1')")
        db.execute("""INSERT INTO replays (replay_id, match_key, match_date, status, created_at, updated_at)
                      VALUES ('old', 'old-match', '2026-10-30T18:00:00Z', 'skipped', 'a', 'b')""")
    with Store(path) as store:
        row = store.get_replay("old")
        assert row["status"] == "skipped"
        assert row["result"] is None and row["trio_goals"] is None and row["opponent_goals"] is None
        assert row["player_names"] is None and row["manual_delivered_at"] is None
    with Store(path) as store:
        assert store.get_replay("old")["status"] == "skipped"


@pytest.mark.parametrize(("status", "attempts", "reason", "consumed"), [
    ("generated", 0, None, True), ("posting", 0, None, True),
    ("posted", 0, None, True), ("skipped", 0, None, True),
    ("analysis_failed", 1, "ai_failed", False), ("analysis_failed", 2, "ai_failed", True),
    ("analysis_failed", 1, "analysis_in_progress", True), ("unknown", 0, None, True),
])
def test_replay_and_match_consumption(tmp_path, status, attempts, reason, consumed):
    with Store(tmp_path / "test.sqlite3") as store:
        seed(store, "upload-1", "match-1", status, attempts, reason)
        assert store.replay_is_consumed("upload-1") is consumed
        assert store.match_is_consumed("match-1", exclude_replay_id="upload-2") is consumed
        assert not store.match_is_consumed("match-1", exclude_replay_id="upload-1")
        assert not store.replay_is_consumed("missing")


def test_record_duplicate_preserves_original_and_is_idempotent(tmp_path):
    replay = {"id": "upload-2", "match_guid": "match-1", "date": "2026-10-30T20:00:00+02:00"}
    with Store(tmp_path / "test.sqlite3") as store:
        seed(store, "upload-1", "match-1", "posted")
        store.record_duplicate(replay, "match-1", now=NOW)
        store.record_duplicate(replay, "match-1", now=NOW)
        duplicate = store.get_replay("upload-2")
        assert duplicate["status"] == "skipped"
        assert duplicate["reason"] == "duplicate_match"
        assert duplicate["match_date"] == "2026-10-30T18:00:00.000000Z"
        assert duplicate["match_guid"] == "match-1"
        assert store.get_replay("upload-1")["status"] == "posted"
        assert store._connection.execute("SELECT COUNT(*) FROM replays").fetchone()[0] == 2


def test_duplicate_updates_retriable_failure_without_overwriting_terminal_row(tmp_path):
    replay = {"id": "upload-2", "date": "2026-10-30T18:00:00Z"}
    with Store(tmp_path / "test.sqlite3") as store:
        seed(store, "upload-1", "match-1", "posted")
        seed(store, "upload-2", "match-1", "analysis_failed", 1, "ai_failed")
        store.record_duplicate(replay, "match-1", now=NOW)
        assert store.get_replay("upload-2")["reason"] == "duplicate_match"
        assert store.get_replay("upload-2")["attempts"] == 1
        store.record_duplicate({"id": "upload-1", "date": replay["date"]}, "match-1", now=NOW)
        assert store.get_replay("upload-1")["status"] == "posted"


def test_duplicate_requires_original_and_valid_date(tmp_path):
    with Store(tmp_path / "test.sqlite3") as store:
        with pytest.raises(StoreError, match="consumed original"):
            store.record_duplicate({"id": "other", "date": "2026-10-30T18:00:00Z"}, "match-1", now=NOW)
        with pytest.raises(StoreError, match="date"):
            store.record_duplicate({"id": "other", "date": "bad"}, "match-1", now=NOW)
        assert store.get_replay("other") is None


def test_inflight_analysis_blocks_match_without_marking_other_upload_terminal(tmp_path):
    with Store(tmp_path / "test.sqlite3") as store:
        seed(store, "upload-1", "match-1", "analysis_failed", 1, "analysis_in_progress")
        assert store.match_is_consumed("match-1", exclude_replay_id="upload-2")
        store.record_duplicate({"id": "upload-2", "date": "2026-10-30T18:00:00Z"}, "match-1", now=NOW)
        assert store.get_replay("upload-2") is None


def test_analysis_reservation_blocks_other_uploads_and_survives_reopen(tmp_path, replay):
    path = tmp_path / "test.sqlite3"
    duplicate = {**replay, "id": "duplicate-upload"}
    with Store(path) as first, Store(path) as second:
        reserved = first.reserve_analysis(replay, provider="mock", model="test", now=NOW)
        assert reserved["status"] == "analysis_failed"
        assert reserved["reason"] == "analysis_in_progress"
        assert reserved["attempts"] == 1
        assert [row["replay_id"] for row in first.inflight_analyses()] == [replay["id"]]
        assert second.match_is_consumed("match-1", exclude_replay_id="duplicate-upload")
        with pytest.raises(StoreError, match="already consumed or analysis is in progress"):
            second.reserve_analysis(duplicate, now=NOW)
    with Store(path) as reopened:
        with pytest.raises(StoreError, match="analysis is in progress"):
            reopened.reserve_analysis(replay, now=NOW)


def test_failed_attempts_reuse_original_row_and_reach_cap(tmp_path, replay):
    with Store(tmp_path / "test.sqlite3") as store:
        first = store.reserve_analysis(replay, now=NOW)
        failed = store.mark_analysis_failed(first["replay_id"], now=NOW)
        assert failed["status"] == "analysis_failed"
        assert failed["reason"] == "ai_failed"
        assert failed["attempts"] == 1
        assert not store.match_is_consumed("match-1", exclude_replay_id="duplicate")
        second = store.reserve_analysis({**replay, "id": "duplicate"}, now=NOW)
        assert second["replay_id"] == replay["id"]
        assert second["attempts"] == 2
        failed = store.mark_analysis_failed(second["replay_id"], now=NOW)
        assert failed["status"] == "skipped"
        assert failed["reason"] == "ai_failed"
        assert store.get_replay("duplicate") is None
        with pytest.raises(StoreError, match="already consumed"):
            store.reserve_analysis({**replay, "id": "another-upload"}, now=NOW)


def test_generated_text_is_persisted_and_blocks_duplicate_ai(tmp_path, replay):
    path = tmp_path / "test.sqlite3"
    text = "Ali won 3-2 with two demos. #RocketLeague"
    with Store(path) as store:
        reservation = store.reserve_analysis(replay, provider="mock", model="test", now=NOW)
        generated = store.save_generated(reservation["replay_id"], text, now=NOW)
        assert generated["status"] == "generated"
        assert generated["tweet_text"] == text
        assert generated["provider"] == "mock"
        assert generated["model"] == "test"
        assert generated["reason"] is None
        with pytest.raises(StoreError, match="already consumed"):
            store.reserve_analysis({**replay, "id": "duplicate"}, now=NOW)
        with pytest.raises(StoreError, match="No reserved"):
            store.save_generated(replay["id"], text, now=NOW)
    with Store(path, readonly=True) as store:
        assert store.get_replay(replay["id"])["tweet_text"] == text


def test_analysis_transitions_require_reservation_and_nonempty_text(tmp_path, replay):
    with Store(tmp_path / "test.sqlite3") as store:
        with pytest.raises(StoreError, match="No reserved"):
            store.mark_analysis_failed(replay["id"], now=NOW)
        store.reserve_analysis(replay, now=NOW)
        with pytest.raises(StoreError, match="text is required"):
            store.save_generated(replay["id"], "  ", now=NOW)
        assert store.get_replay(replay["id"])["reason"] == "analysis_in_progress"


def test_same_replay_id_cannot_be_rebound_to_different_match(tmp_path, replay):
    with Store(tmp_path / "test.sqlite3") as store:
        store.reserve_analysis(replay, now=NOW)
        with pytest.raises(StoreError, match="different match"):
            store.reserve_analysis({**replay, "match_guid": "different"}, now=NOW)


def test_match_result_and_score_are_saved_for_future_history(tmp_path, replay, config):
    from rl_analyzer.stats import extract_stats

    match = extract_stats(replay, config.players)["match"]
    with Store(tmp_path / "test.sqlite3") as store:
        row = store.reserve_analysis(replay, match=match, names=["Ali", "Alias A"], now=NOW)
        assert (row["result"], row["trio_goals"], row["opponent_goals"]) == ("win", 3, 2)
        assert row["player_names"] == '["Ali", "Alias A"]'
        store.mark_analysis_failed(replay["id"], now=NOW)
        conflicting = {**match, "result": "draw", "score": {"trio": 3, "opponents": 3}}
        with pytest.raises(StoreError, match="conflicts"):
            store.reserve_analysis({**replay, "id": "duplicate"}, match=conflicting, now=NOW)
        assert store.get_replay(replay["id"])["attempts"] == 1
        row = store.reserve_analysis({**replay, "id": "duplicate"}, match=match, now=NOW)
        assert (row["result"], row["trio_goals"], row["opponent_goals"]) == ("win", 3, 2)


@pytest.mark.parametrize("match", [
    {"result": "win", "score": {"trio": 2, "opponents": 2}},
    {"result": "win", "score": {"trio": True, "opponents": 0}},
    {"result": "win", "score": {"trio": -1, "opponents": 0}},
    {"result": "win", "score": {}},
])
def test_invalid_history_metadata_fails_without_writing(tmp_path, replay, match):
    with Store(tmp_path / "test.sqlite3") as store:
        with pytest.raises(StoreError, match="result and score"):
            store.reserve_analysis(replay, match=match, now=NOW)
        assert store.get_replay(replay["id"]) is None


def test_two_retryable_rows_for_one_match_fail_safely(tmp_path, replay):
    with Store(tmp_path / "test.sqlite3") as store:
        seed(store, "first", "match-1", "analysis_failed", 1, "ai_failed")
        seed(store, "second", "match-1", "analysis_failed", 1, "ai_failed")
        with pytest.raises(StoreError, match="require inspection"):
            store.reserve_analysis(replay, now=NOW)


@pytest.mark.parametrize("attempts", [-1, 0])
def test_corrupt_retry_count_fails_closed(tmp_path, replay, attempts):
    with Store(tmp_path / "test.sqlite3") as store:
        seed(store, "first", "match-1", "analysis_failed", attempts, "ai_failed")
        with pytest.raises(StoreError, match="attempt count requires inspection"):
            store.reserve_analysis(replay, now=NOW)


def test_database_readonly_blocks_reservations(tmp_path, replay):
    path = tmp_path / "test.sqlite3"
    with Store(path):
        pass
    before = path.read_bytes()
    with Store(path, readonly=True) as store:
        with pytest.raises(StoreError, match="read-only"):
            store.reserve_analysis(replay, now=NOW)
    assert path.read_bytes() == before


def test_simultaneous_duplicate_reservations_only_allow_one(tmp_path, replay):
    path = tmp_path / "test.sqlite3"
    with Store(path):
        pass
    barrier = Barrier(2)

    def attempt(replay_id):
        with Store(path) as store:
            barrier.wait(timeout=10)
            try:
                store.reserve_analysis({**replay, "id": replay_id}, now=NOW)
                return "reserved"
            except StoreError:
                return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["upload-a", "upload-b"]))
    assert sorted(outcomes) == ["blocked", "reserved"]
    with Store(path) as store:
        assert store._connection.execute("SELECT COUNT(*) FROM replays WHERE match_key='match-1'").fetchone()[0] == 1
