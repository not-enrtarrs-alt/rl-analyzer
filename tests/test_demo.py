"""The demo is offline, independent of .env and uses no database."""

import json
from unittest.mock import Mock

from rl_analyzer.demo import run_demo
from rl_analyzer.tweet import weighted_length


def test_demo_works_offline_without_env_or_database(tmp_path, monkeypatch):
    monkeypatch.setenv("POST_TO_X", "true")
    monkeypatch.setenv("CLIPBOARD_ENABLED", "false")
    monkeypatch.setattr("requests.sessions.Session.request", Mock(side_effect=AssertionError("network")))
    assert run_demo(output_dir=tmp_path / "out") == 0
    tweet = (tmp_path / "out" / "demo_tweet.txt").read_text(encoding="utf-8")
    assert "3-2" in tweet and "Ali" in tweet and tweet.endswith("#RocketLeague")
    assert weighted_length(tweet) <= 280
    metadata = json.loads((tmp_path / "out" / "last_run.json").read_text(encoding="utf-8"))
    assert metadata["provider"] == "mock" and metadata["status"] == "demo"
    assert not list(tmp_path.rglob("*.sqlite3"))


def test_demo_missing_fixture_fails_safely(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPBOARD_ENABLED", "false")
    assert run_demo(output_dir=tmp_path / "out", fixture_path=tmp_path / "missing.json") == 6
