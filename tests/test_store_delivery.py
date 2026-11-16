"""Delivery, posting and cooldown state tests."""

from datetime import datetime, timedelta, timezone

import pytest

from rl_analyzer.store import Store, StoreError

NOW = datetime(2026, 10, 30, 19, tzinfo=timezone.utc)

def generate(store, replay, text="Ali won 3-2 with two demos. #RocketLeague"):
    row = store.reserve_analysis(replay, provider="mock", model="test", now=NOW)
    return store.save_generated(row["replay_id"], text, now=NOW)


def test_pending_returns_newest_cached_text_and_known_post_failure_reuses_it(tmp_path, replay):
    path = tmp_path / "test.sqlite3"
    older = {**replay, "id": "older", "match_guid": "older-match", "rocket_league_id": "older-game", "date": "2026-10-30T17:00:00Z"}
    with Store(path) as store:
        generate(store, replay)
        generate(store, older, text="Bea won 3-2 with a demo. #RocketLeague")
        pending = store.latest_pending()
        assert pending["replay_id"] == replay["id"]
        text = pending["tweet_text"]
        assert store.start_posting(replay["id"], now=NOW)["status"] == "posting"
        failed = store.mark_post_failed(replay["id"], outcome_known=True, now=NOW)
        assert failed["status"] == "generated"
        assert failed["tweet_text"] == text
        assert failed["attempts"] == 1
    with Store(path) as store:
        assert store.latest_pending()["tweet_text"] == text
        store.start_posting(replay["id"], now=NOW)
        posted = store.mark_posted(replay["id"], "tweet-1", now=NOW)
        assert posted["status"] == "posted"
        assert posted["tweet_text"] == text
        assert posted["tweet_id"] == "tweet-1"
        assert store.latest_pending()["replay_id"] == "older"
        assert store._connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
        assert store._connection.execute("SELECT value FROM meta WHERE key='last_success_at'").fetchone()[0] == "2026-10-30T19:00:00.000000Z"


def test_crashed_and_unknown_posts_block_all_new_posts(tmp_path, replay):
    path = tmp_path / "test.sqlite3"
    other = {**replay, "id": "other", "match_guid": "other-match", "rocket_league_id": "other-game"}
    with Store(path) as store:
        generate(store, replay)
        generate(store, other)
        store.start_posting(replay["id"], now=NOW)
    with Store(path) as store:
        assert store.posting_rows()[0]["replay_id"] == replay["id"]
        with pytest.raises(StoreError, match="requires inspection"):
            store.start_posting("other", now=NOW)
        unknown = store.mark_post_failed(replay["id"], outcome_known=False, now=NOW)
        assert unknown["status"] == "posting"
        assert unknown["reason"] == "posting_unknown"
        with pytest.raises(StoreError, match="requires inspection"):
            store.start_posting(replay["id"], now=NOW)
        with pytest.raises(StoreError, match="manual inspection"):
            store.mark_post_failed(replay["id"], outcome_known=True, now=NOW)


def test_confirm_post_is_idempotent_and_tweet_id_unique(tmp_path, replay):
    other = {**replay, "id": "other", "match_guid": "other-match", "rocket_league_id": "other-game"}
    with Store(tmp_path / "test.sqlite3") as store:
        generate(store, replay)
        store.start_posting(replay["id"], now=NOW)
        store.mark_posted(replay["id"], "tweet-1", now=NOW)
        store.mark_posted(replay["id"], "tweet-1", now=NOW)
        generate(store, other)
        store.start_posting("other", now=NOW)
        with pytest.raises(StoreError, match="already recorded"):
            store.mark_posted("other", "tweet-1", now=NOW)
        assert store.get_replay("other")["status"] == "posting"
        assert store._connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1


def test_invalid_post_transitions_and_missing_tweet_id(tmp_path, replay):
    with Store(tmp_path / "test.sqlite3") as store:
        with pytest.raises(StoreError, match="No generated"):
            store.start_posting(replay["id"], now=NOW)
        generate(store, replay)
        with pytest.raises(StoreError, match="No in-flight"):
            store.mark_posted(replay["id"], "tweet-1", now=NOW)
        store.start_posting(replay["id"], now=NOW)
        with pytest.raises(StoreError, match="tweet ID"):
            store.mark_posted(replay["id"], "", now=NOW)
        assert store.get_replay(replay["id"])["status"] == "posting"


def test_expired_pending_is_terminal_without_losing_text(tmp_path, replay):
    with Store(tmp_path / "test.sqlite3") as store:
        generated = generate(store, replay)
        skipped = store.skip_expired(replay["id"], now=NOW)
        assert skipped["status"] == "skipped"
        assert skipped["reason"] == "expired_before_post"
        assert skipped["tweet_text"] == generated["tweet_text"]
        assert store.latest_pending() is None
        with pytest.raises(StoreError, match="No generated"):
            store.start_posting(replay["id"], now=NOW)
        with pytest.raises(StoreError, match="already consumed"):
            store.reserve_analysis({**replay, "id": "duplicate"}, now=NOW)


def test_manual_delivery_sets_cooldown_without_creating_post(tmp_path, replay):
    path = tmp_path / "test.sqlite3"
    with Store(path) as store:
        assert store.last_success_at() is None
        assert not store.in_cooldown(NOW, 20)
        generate(store, replay)
        assert store.latest_undelivered()["replay_id"] == replay["id"]
        result = store.mark_manual_delivered(replay["id"], now=NOW)
        assert result["status"] == "generated"
        assert result["manual_delivered_at"] == "2026-10-30T19:00:00.000000Z"
        assert store.latest_undelivered() is None
        assert store.last_success_at() == NOW
        assert store.in_cooldown(NOW + timedelta(hours=19, minutes=59), 20)
        assert not store.in_cooldown(NOW + timedelta(hours=20), 20)
        assert store.in_cooldown(NOW - timedelta(hours=1), 20)
        assert store._connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
    with Store(path, readonly=True) as store:
        assert store.in_cooldown(NOW + timedelta(hours=1), 20)


def test_cooldown_uses_later_of_meta_and_latest_post(tmp_path, replay):
    with Store(tmp_path / "test.sqlite3") as store:
        generate(store, replay)
        store.start_posting(replay["id"], now=NOW)
        store.mark_posted(replay["id"], "tweet-1", now=NOW + timedelta(hours=2))
        with store._connection:
            store._connection.execute("UPDATE meta SET value=? WHERE key='last_success_at'", ("2026-10-30T19:00:00Z",))
        assert store.last_success_at() == NOW + timedelta(hours=2)
        assert store.in_cooldown(NOW + timedelta(hours=21), 20)
        with store._connection:
            store._connection.execute("UPDATE meta SET value=? WHERE key='last_success_at'", ("2026-10-30T22:00:00Z",))
        assert store.last_success_at() == NOW + timedelta(hours=3)
        assert not store.in_cooldown(NOW + timedelta(hours=23), 20)


def test_manual_success_time_never_moves_backwards(tmp_path, replay):
    with Store(tmp_path / "test.sqlite3") as store:
        generate(store, replay)
        store.mark_manual_delivered(replay["id"], now=NOW)
        store.mark_manual_delivered(replay["id"], now=NOW - timedelta(hours=1))
        assert store.last_success_at() == NOW


def test_invalid_cooldown_or_corrupt_timestamp_fails_closed(tmp_path, replay):
    with Store(tmp_path / "test.sqlite3") as store:
        with pytest.raises(StoreError, match="timezone"):
            store.in_cooldown(datetime(2026, 10, 30), 20)
        with pytest.raises(StoreError, match="positive"):
            store.in_cooldown(NOW, 0)
        with pytest.raises(StoreError, match="too large"):
            store.in_cooldown(NOW, 10 ** 400)
        with store._connection:
            store._connection.execute("INSERT INTO meta VALUES ('last_success_at', 'bad')")
        with pytest.raises(StoreError, match="timestamp is invalid"):
            store.in_cooldown(NOW, 20)
        generate(store, replay)
        with pytest.raises(StoreError, match="timestamp is invalid"):
            store.mark_manual_delivered(replay["id"], now=NOW)
        assert store.get_replay(replay["id"])["status"] == "generated"


def test_manual_delivery_requires_generated_state(tmp_path, replay):
    with Store(tmp_path / "test.sqlite3") as store:
        with pytest.raises(StoreError, match="manual delivery"):
            store.mark_manual_delivered(replay["id"], now=NOW)
        generate(store, replay)
        store.start_posting(replay["id"], now=NOW)
        with pytest.raises(StoreError, match="manual delivery"):
            store.mark_manual_delivered(replay["id"], now=NOW)
        assert store.last_success_at() is None


def test_corrupt_cooldown_rolls_back_confirmed_post_record(tmp_path, replay):
    with Store(tmp_path / "test.sqlite3") as store:
        generate(store, replay)
        with store._connection:
            store._connection.execute("INSERT INTO meta VALUES ('last_success_at', 'bad')")
        store.start_posting(replay["id"], now=NOW)
        with pytest.raises(StoreError, match="timestamp is invalid"):
            store.mark_posted(replay["id"], "tweet-1", now=NOW)
        assert store.get_replay(replay["id"])["status"] == "posting"
        assert store._connection.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 0
