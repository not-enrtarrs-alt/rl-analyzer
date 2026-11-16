"""History is read-only and does not require credentials or network access."""

from datetime import datetime, timezone

from rl_analyzer import cli
from rl_analyzer.stats import extract_stats
from rl_analyzer.store import Store

NOW = datetime(2026, 10, 30, 19, tzinfo=timezone.utc)


def test_empty_history_does_not_create_database(config, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda **kw: config)
    assert cli.main(["history"]) == 0
    assert "No history yet" in capsys.readouterr().out
    assert not config.database_path.exists()


def test_history_shows_recent_result_status_and_tweet(config, replay, monkeypatch, capsys):
    with Store(config.database_path) as store:
        stats = extract_stats(replay, config.players)
        store.reserve_analysis(replay, match=stats["match"], now=NOW)
        store.save_generated(replay["id"], "Ali won 3-2 with two demos. #RocketLeague", now=NOW)
        store.start_posting(replay["id"], now=NOW)
        store.mark_posted(replay["id"], "tweet-1", now=NOW)
        older = {**replay, "id": "older", "match_guid": "older-match", "rocket_league_id": "older-game", "date": "2026-10-30T17:00:00Z"}
        store.reserve_analysis(older, match=stats["match"], now=NOW)
        store.mark_analysis_failed("older", now=NOW)
    before = config.database_path.read_bytes()
    monkeypatch.setattr(cli, "load_config", lambda **kw: config)
    assert cli.main(["history", "--limit", "1"]) == 0
    output = capsys.readouterr().out
    assert "win 3-2" in output and "posted" in output and "tweet-1" in output
    assert "Ali won 3-2" in output and "analysis_failed" not in output
    assert config.database_path.read_bytes() == before


def test_history_corrupt_db_fails_safely(config, monkeypatch, capsys):
    config.database_path.parent.mkdir(parents=True)
    config.database_path.write_text("invalid", encoding="utf-8")
    monkeypatch.setattr(cli, "load_config", lambda **kw: config)
    assert cli.main(["history"]) == 6
    assert "cannot be read" in capsys.readouterr().out
