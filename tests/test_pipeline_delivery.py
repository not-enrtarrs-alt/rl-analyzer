"""Cached delivery integrates temporary storage with a fake X client."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from rl_analyzer.pipeline_delivery import deliver_cached, deliver_pending
from rl_analyzer.stats import extract_stats
from rl_analyzer.store import Store
from rl_analyzer.x_client import XClient, XError

NOW = datetime(2026, 10, 30, 19, tzinfo=timezone.utc)
TEXT = "Ali won 3-2 with 2 demos. #RocketLeague"


def generated(store, replay, config, provider="ollama"):
    stats = extract_stats(replay, config.players)
    names = [name for player in stats["players"] for name in (player["alias"], player["in_game_name"]) if name]
    reserved = store.reserve_analysis(replay, match=stats["match"], names=names, provider=provider, now=NOW)
    return store.save_generated(reserved["replay_id"], TEXT, now=NOW)


def test_post_failure_retains_cached_text_then_success(tmp_path, config, replay):
    config = replace(config, post_to_x=True, ai_provider="ollama", manual_output_dir=tmp_path / "out")
    client = Mock()
    client.post.side_effect = [XError("rate limit", outcome_known=True), "tweet-1"]
    with Store(tmp_path / "db.sqlite3") as store:
        generated(store, replay, config)
        assert deliver_pending(config, store, NOW, x_client=client) == 5
        assert store.latest_pending()["tweet_text"] == TEXT
        assert store.latest_pending()["attempts"] == 1
        assert deliver_pending(config, store, NOW, x_client=client) == 0
        assert store.get_replay(replay["id"])["status"] == "posted"
        assert store.last_success_at() == NOW
        assert len(list((tmp_path / "out" / "posted").glob("*.txt"))) == 1
        assert client.post.call_count == 2


def test_unknown_post_outcome_remains_guarded(tmp_path, config, replay):
    config = replace(config, post_to_x=True, ai_provider="ollama")
    client = Mock()
    client.post.side_effect = XError("timeout", outcome_known=False)
    with Store(tmp_path / "db.sqlite3") as store:
        generated(store, replay, config)
        assert deliver_pending(config, store, NOW, x_client=client) == 5
        assert store.get_replay(replay["id"])["reason"] == "posting_unknown"
        assert store.latest_pending() is None
        assert store.posting_rows()


def test_expired_cached_row_skipped_without_post(tmp_path, config, replay):
    config = replace(config, post_to_x=True, ai_provider="ollama")
    client = Mock()
    with Store(tmp_path / "db.sqlite3") as store:
        generated(store, replay, config)
        assert deliver_pending(config, store, NOW + timedelta(hours=49), x_client=client) is None
        assert store.get_replay(replay["id"])["reason"] == "expired_before_post"
        client.post.assert_not_called()


def test_manual_pending_writes_once_and_sets_cooldown(tmp_path, config, replay):
    config = replace(config, manual_output_dir=tmp_path / "out")
    with Store(tmp_path / "db.sqlite3") as store:
        generated(store, replay, config)
        assert deliver_pending(config, store, NOW) == 0
        assert (tmp_path / "out" / "tweet.txt").read_text(encoding="utf-8") == TEXT
        assert store.last_success_at() == NOW
        assert store.get_replay(replay["id"])["status"] == "generated"
        assert deliver_pending(config, store, NOW) is None


def test_unsafe_cached_text_never_posts(tmp_path, config, replay):
    config = replace(config, post_to_x=True, ai_provider="ollama")
    client = Mock()
    with Store(tmp_path / "db.sqlite3") as store:
        row = generated(store, replay, config)
        row["tweet_text"] = "Ali won 3-2 https://example.com #RocketLeague"
        assert deliver_cached(row, config, store, NOW, x_client=client) == 5
        assert store.get_replay(replay["id"])["status"] == "generated"
        client.post.assert_not_called()


def test_mock_generated_text_is_never_posted(tmp_path, config, replay):
    config = replace(config, post_to_x=True)
    client = Mock()
    with Store(tmp_path / "db.sqlite3") as store:
        row = generated(store, replay, config, provider="mock")
        assert deliver_cached(row, config, store, NOW, x_client=client) == 5
        client.post.assert_not_called()


def test_cooldown_uses_actual_post_completion_time(tmp_path, config, replay):
    config = replace(config, post_to_x=True, ai_provider="ollama", manual_output_dir=tmp_path / "out")
    client = Mock()
    client.post.return_value = "tweet-1"
    completed = NOW + timedelta(seconds=30)
    with Store(tmp_path / "db.sqlite3") as store:
        row = generated(store, replay, config)
        assert deliver_cached(row, config, store, NOW, x_client=client, clock=lambda: completed) == 0
        assert store.last_success_at() == completed


@pytest.mark.parametrize(("status", "phrase", "known"), [
    (401, "authentication failed", True), (403, "Read and write", True),
    (429, "rate limited", True), (500, "server error", False),
])
def test_safe_http_diagnostic_preserves_state(tmp_path, config, replay, monkeypatch, status, phrase, known):
    config = replace(config, post_to_x=True, ai_provider="ollama", x_api_key="key", x_api_secret="dummy-secret",
                     x_access_token="token", x_access_secret="access-secret")
    session = Mock()
    session.post.return_value = Mock(status_code=status, json=Mock(return_value={"detail": "dummy-secret"}))
    error_log = Mock()
    monkeypatch.setattr("rl_analyzer.pipeline_delivery.logger.error", error_log)
    with Store(tmp_path / "db.sqlite3") as store:
        generated(store, replay, config)
        assert deliver_pending(config, store, NOW, x_client=XClient(config, session=session)) == 5
        row = store.get_replay(replay["id"])
        assert row["status"] == ("generated" if known else "posting")
        assert row["tweet_text"] == TEXT
        assert row["reason"] == ("post_failed" if known else "posting_unknown")
        message, *args = error_log.call_args.args
        rendered = message % tuple(args)
        assert f"X HTTP {status}" in rendered and phrase in rendered
        assert "dummy-secret" not in rendered and TEXT not in rendered
        session.post.assert_called_once()


def test_untrusted_x_error_message_is_never_logged(tmp_path, config, replay, monkeypatch):
    config = replace(config, post_to_x=True, ai_provider="ollama")
    client = Mock()
    client.post.side_effect = XError("dummy-secret", outcome_known=True)
    error_log = Mock()
    monkeypatch.setattr("rl_analyzer.pipeline_delivery.logger.error", error_log)
    with Store(tmp_path / "db.sqlite3") as store:
        generated(store, replay, config)
        assert deliver_pending(config, store, NOW, x_client=client) == 5
    message, *args = error_log.call_args.args
    assert "dummy-secret" not in (message % tuple(args))


def test_known_problem_logged_without_response_details(tmp_path, config, replay, monkeypatch):
    config = replace(config, post_to_x=True, ai_provider="ollama", x_api_key="key", x_api_secret="dummy-secret",
                     x_access_token="token", x_access_secret="access-secret")
    session = Mock()
    session.post.return_value = Mock(status_code=403, json=Mock(return_value={
        "type": "https://api.x.com/2/problems/client-forbidden", "detail": "dummy-secret"}))
    error_log = Mock()
    monkeypatch.setattr("rl_analyzer.pipeline_delivery.logger.error", error_log)
    with Store(tmp_path / "db.sqlite3") as store:
        generated(store, replay, config)
        assert deliver_pending(config, store, NOW, x_client=XClient(config, session=session)) == 5
        assert store.latest_pending()["tweet_text"] == TEXT
    message, *args = error_log.call_args.args
    rendered = message % tuple(args)
    assert "X HTTP 403 (client-forbidden)" in rendered and "not enrolled" in rendered
    assert "dummy-secret" not in rendered and TEXT not in rendered
