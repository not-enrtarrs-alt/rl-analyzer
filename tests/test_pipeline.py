"""Daily pipeline tests use fake providers, fake X clients and temporary files."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import Mock

import pytest

from rl_analyzer.ai.base import AIError
from rl_analyzer.delivery import DeliveryError
from rl_analyzer.pipeline import run_daily
from rl_analyzer.run_lock import RunLock
from rl_analyzer.stats import extract_stats
from rl_analyzer.store import Store
from rl_analyzer.x_client import XError

NOW = datetime(2026, 10, 30, 19, tzinfo=timezone.utc)
RAW = "Ali won 3-2 with 2 demos while Cam supported emotionally."
FINAL = RAW + " #RocketLeague"


class FakeClient:
    def __init__(self, *details):
        self.details = {item["id"]: item for item in details}
        self.lists = 0
        self.gets = []

    def list_common_replays(self, ids, cutoff):
        self.lists += 1
        return [{key: value for key, value in item.items() if key in {"id", "date", "playlist_id", "match_guid", "rocket_league_id"}}
                for item in self.details.values()]

    def get_replay(self, replay_id):
        self.gets.append(replay_id)
        return self.details[replay_id]


class FakeAI:
    def __init__(self, result=RAW):
        self.result = result
        self.calls = 0

    def generate(self, system, user):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def run(config, tmp_path, *, client=None, provider=None, x_client=None, **kwargs):
    return run_daily(config=config, client=client, provider=provider, x_client=x_client,
                     lock_path=tmp_path / "run.lock", clock=lambda: NOW, **kwargs)


def seed_generated(store, replay, config, *, provider="ollama"):
    stats = extract_stats(replay, config.players)
    names = [name for p in stats["players"] for name in (p["alias"], p["in_game_name"]) if name]
    row = store.reserve_analysis(replay, match=stats["match"], names=names, provider=provider, now=NOW)
    return store.save_generated(row["replay_id"], FINAL, now=NOW)


def test_no_candidate_no_ai_call(config, tmp_path):
    ai = FakeAI()
    assert run(config, tmp_path, client=FakeClient(), provider=ai) == 0
    assert ai.calls == 0


def test_posted_match_never_reanalyzed(config, tmp_path, replay):
    config = replace(config, ai_provider="ollama")
    with Store(config.database_path) as store:
        seed_generated(store, replay, config)
        store.start_posting(replay["id"], now=NOW)
        store.mark_posted(replay["id"], "fake-tweet", now=NOW)
    ai = FakeAI()
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, force=True) == 0
    assert ai.calls == 0


def test_ai_failure_no_post_and_no_template(config, tmp_path, replay):
    config = replace(config, post_to_x=True, ai_provider="ollama")
    ai, x = FakeAI(AIError("provider failed")), Mock()
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, x_client=x) == 4
    assert ai.calls == 1
    x.post.assert_not_called()
    with Store(config.database_path) as store:
        row = store.get_replay(replay["id"])
        assert (row["status"], row["attempts"], row["tweet_text"]) == ("analysis_failed", 1, None)
    assert not (config.manual_output_dir / "tweet.txt").exists()


def test_provider_error_never_leaks_details_in_logs(config, tmp_path, replay):
    ai = FakeAI(AIError("dummy-secret"))
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai) == 4
    log = (config.log_dir / "rl_analyzer.log").read_text(encoding="utf-8")
    assert "dummy-secret" not in log


def test_validation_error_logs_only_safe_category(config, tmp_path, replay):
    ai = FakeAI("Ali played brilliantly and had two demos.")
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai) == 4
    log = (config.log_dir / "rl_analyzer.log").read_text(encoding="utf-8")
    assert "validation after retry: score" in log
    assert "Ali played" not in log


def test_post_failure_reuses_cache_next_run_without_ai_or_api(config, tmp_path, replay):
    config = replace(config, post_to_x=True, ai_provider="ollama")
    ai, x = FakeAI(), Mock()
    x.post.side_effect = [XError("rate limited", outcome_known=True), "tweet-1"]
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, x_client=x) == 5
    assert ai.calls == 1
    no_api, no_ai = FakeClient(), FakeAI(AIError("must not run"))
    assert run(config, tmp_path, client=no_api, provider=no_ai, x_client=x) == 0
    assert no_api.lists == 0 and no_ai.calls == 0
    assert x.post.call_count == 2 and x.post.call_args.args == (FINAL,)
    with Store(config.database_path) as store:
        assert store.get_replay(replay["id"])["status"] == "posted"


def test_cooldown_blocks_and_force_allows_new_game(config, tmp_path, replay):
    first, second = dict(replay), {**replay, "id": "older", "match_guid": "older-match", "rocket_league_id": "older-game", "date": "2026-10-30T17:00:00Z"}
    ai = FakeAI()
    assert run(config, tmp_path, client=FakeClient(first), provider=ai) == 0
    other = FakeAI()
    client = FakeClient(second)
    assert run(config, tmp_path, client=client, provider=other) == 0
    assert client.lists == 0 and other.calls == 0
    assert run(config, tmp_path, client=client, provider=other, force=True) == 0
    assert other.calls == 1


def test_dry_run_no_database_creation_or_mutation(config, tmp_path, replay):
    config = replace(config, post_to_x=True)
    ai, x = FakeAI(), Mock()
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, x_client=x, dry_run=True) == 0
    assert not config.database_path.exists()
    assert (config.manual_output_dir / "tweet.txt").read_text(encoding="utf-8") == FINAL
    assert json.loads((config.manual_output_dir / "last_run.json").read_text(encoding="utf-8"))["status"] == "dry_run"
    x.post.assert_not_called()
    with Store(config.database_path) as store:
        pass
    before = config.database_path.read_bytes()
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, dry_run=True) == 0
    assert config.database_path.read_bytes() == before


def test_preview_specific_id_fetches_only_detail(config, tmp_path, replay):
    api, ai = FakeClient(replay), FakeAI()
    assert run(config, tmp_path, client=api, provider=ai, dry_run=True, replay_id=replay["id"]) == 0
    assert api.lists == 0 and api.gets == [replay["id"]] and ai.calls == 1
    assert not config.database_path.exists()


def test_preview_specific_consumed_replay_never_calls_ai(config, tmp_path, replay):
    with Store(config.database_path) as store:
        seed_generated(store, replay, config)
    ai = FakeAI()
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, dry_run=True, replay_id=replay["id"]) == 0
    assert ai.calls == 0


def test_fresh_lock_is_noop(config, tmp_path, replay):
    ai = FakeAI()
    with RunLock(tmp_path / "run.lock") as acquired:
        assert acquired
        assert run(config, tmp_path, client=FakeClient(replay), provider=ai) == 0
    assert ai.calls == 0 and not config.database_path.exists()


def test_failed_manual_delivery_reuses_cache(config, tmp_path, replay, monkeypatch):
    import rl_analyzer.pipeline_delivery as module

    original = module.deliver_tweet
    monkeypatch.setattr(module, "deliver_tweet", Mock(side_effect=DeliveryError("file error")))
    ai = FakeAI()
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai) == 6
    assert ai.calls == 1
    monkeypatch.setattr(module, "deliver_tweet", original)
    no_ai, no_api = FakeAI(AIError("must not run")), FakeClient()
    assert run(config, tmp_path, client=no_api, provider=no_ai) == 0
    assert no_ai.calls == 0 and no_api.lists == 0
    assert (config.manual_output_dir / "tweet.txt").read_text(encoding="utf-8") == FINAL


def test_expired_pending_skipped_before_selecting_fresh(config, tmp_path, replay):
    old = {**replay, "id": "old", "match_guid": "old-match", "rocket_league_id": "old-game", "date": (NOW - timedelta(hours=49)).isoformat()}
    with Store(config.database_path) as store:
        seed_generated(store, old, config)
    ai = FakeAI()
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai) == 0
    assert ai.calls == 1
    with Store(config.database_path) as store:
        assert store.get_replay("old")["reason"] == "expired_before_post"


def test_inflight_post_blocks_live_pipeline(config, tmp_path, replay):
    config = replace(config, post_to_x=True, ai_provider="ollama")
    with Store(config.database_path) as store:
        seed_generated(store, replay, config)
        store.start_posting(replay["id"], now=NOW)
    ai, x = FakeAI(), Mock()
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, x_client=x, force=True) == 5
    assert ai.calls == 0
    x.post.assert_not_called()


def test_invalid_ai_output_retries_once_per_attempt_then_skips(config, tmp_path, replay):
    config = replace(config, post_to_x=True, ai_provider="ollama")
    ai, x = FakeAI("I cannot help with this request."), Mock()
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, x_client=x) == 4
    assert ai.calls == 2
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, x_client=x, force=True) == 4
    assert ai.calls == 4
    with Store(config.database_path) as store:
        row = store.get_replay(replay["id"])
        assert (row["status"], row["reason"], row["attempts"]) == ("skipped", "ai_failed", 2)
        assert row["tweet_text"] is None
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, x_client=x, force=True) == 0
    assert ai.calls == 4
    x.post.assert_not_called()


def test_uncertain_post_never_retries_automatically(config, tmp_path, replay):
    config = replace(config, post_to_x=True, ai_provider="ollama")
    ai, x = FakeAI(), Mock()
    x.post.side_effect = XError("timeout", outcome_known=False)
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, x_client=x) == 5
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, x_client=x, force=True) == 5
    assert ai.calls == 1 and x.post.call_count == 1
    with Store(config.database_path) as store:
        assert store.get_replay(replay["id"])["reason"] == "posting_unknown"


def test_corrupt_cached_tweet_never_posts_or_regenerates(config, tmp_path, replay):
    config = replace(config, post_to_x=True, ai_provider="ollama")
    with Store(config.database_path) as store:
        seed_generated(store, replay, config)
        with store._connection:
            store._connection.execute("UPDATE replays SET tweet_text=? WHERE replay_id=?",
                                      ("Ali won 3-2 https://example.com #RocketLeague", replay["id"]))
    ai, x = FakeAI(), Mock()
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, x_client=x) == 5
    assert ai.calls == 0
    x.post.assert_not_called()


def test_successful_post_archive_failure_never_reposts(config, tmp_path, replay, monkeypatch):
    import rl_analyzer.pipeline_delivery as module

    config = replace(config, post_to_x=True, ai_provider="ollama")
    monkeypatch.setattr(module, "deliver_tweet", Mock(side_effect=DeliveryError("file error")))
    ai, x = FakeAI(), Mock()
    x.post.return_value = "tweet-1"
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, x_client=x) == 6
    with Store(config.database_path) as store:
        assert store.get_replay(replay["id"])["status"] == "posted"
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, x_client=x, force=True) == 0
    assert ai.calls == 1 and x.post.call_count == 1


def test_mock_provider_is_blocked_for_live_but_allowed_in_preview(config, tmp_path, replay):
    config = replace(config, post_to_x=True, ai_provider="mock")
    ai, x = FakeAI(), Mock()
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, x_client=x) == 2
    assert ai.calls == 0
    x.post.assert_not_called()
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, x_client=x, dry_run=True) == 0
    assert ai.calls == 1
    x.post.assert_not_called()


def test_force_does_not_override_consumed_match(config, tmp_path, replay):
    ai = FakeAI()
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai) == 0
    assert run(config, tmp_path, client=FakeClient(replay), provider=ai, force=True) == 0
    assert ai.calls == 1
