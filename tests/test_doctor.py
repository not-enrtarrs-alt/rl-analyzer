"""Doctor checks never post and offline mode never uses the network."""

from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock

import requests

from rl_analyzer import cli
from rl_analyzer.config import load_config
from rl_analyzer.stats import extract_stats
from rl_analyzer.store import Store

NOW = datetime(2026, 10, 30, 19, tzinfo=timezone.utc)


def test_offline_reports_missing_values_without_network_or_clipboard_contents(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda **kw: load_config(root=tmp_path, env={}, **kw))
    monkeypatch.setattr("rl_analyzer.diagnostics.requests.get", Mock(side_effect=AssertionError("network")))
    paste = Mock(return_value="private clipboard content")
    monkeypatch.setattr("rl_analyzer.diagnostics.pyperclip.paste", paste)
    assert cli.main(["doctor", "--offline"]) == 0
    output = capsys.readouterr().out
    assert "WARNING: Missing BALLCHASING_TOKEN" in output
    assert "Database: not created yet" in output and "Network checks skipped" in output
    assert "private clipboard content" not in output
    assert not (tmp_path / "data").exists() and not (tmp_path / "out").exists()
    paste.assert_called_once()


def test_doctor_reports_posting_and_analysis_guards(config, replay, monkeypatch, capsys):
    with Store(config.database_path) as store:
        stats = extract_stats(replay, config.players)
        store.reserve_analysis(replay, match=stats["match"], now=NOW)
        store.save_generated(replay["id"], "Ali won 3-2 with two demos. #RocketLeague", now=NOW)
        store.start_posting(replay["id"], now=NOW)
        other = {**replay, "id": "other", "match_guid": "other-match", "rocket_league_id": "other-game"}
        store.reserve_analysis(other, match=stats["match"], now=NOW)
    monkeypatch.setattr(cli, "load_config", lambda **kw: config)
    assert cli.main(["doctor", "--offline"]) == 0
    output = capsys.readouterr().out
    assert "1 in-flight or unknown post" in output
    assert "1 in-flight analysis reservation" in output


def test_doctor_bad_database_and_directory_report_errors(config, tmp_path, monkeypatch, capsys):
    bad = tmp_path / "bad.sqlite3"
    bad.write_text("not a database", encoding="utf-8")
    output_path = tmp_path / "file"
    output_path.write_text("existing", encoding="utf-8")
    config = replace(config, database_path=bad, manual_output_dir=output_path)
    monkeypatch.setattr(cli, "load_config", lambda **kw: config)
    assert cli.main(["doctor", "--offline"]) == 6
    output = capsys.readouterr().out
    assert "ERROR: Database cannot be read" in output and "ERROR: Output path" in output
    assert output_path.read_text(encoding="utf-8") == "existing"


class Response:
    def __init__(self, status=200, body=None):
        self.status_code, self.body = status, body

    def json(self):
        return self.body


def test_live_doctor_checks_ballchasing_and_ollama_only(config, monkeypatch, capsys):
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response(body={"models": [{"name": config.ollama_model}]}) if url.endswith("/api/tags") else Response()

    monkeypatch.setattr(cli, "load_config", lambda **kw: config)
    monkeypatch.setattr("rl_analyzer.diagnostics.requests.get", get)
    assert cli.main(["doctor", "--live"]) == 0
    output = capsys.readouterr().out
    assert "authenticated endpoint reachable" in output and "configured model available" in output
    assert len(calls) == 2 and calls[0][0].endswith("/api/")
    assert calls[0][1]["headers"]["Authorization"] == "dummy-secret"
    assert "dummy-secret" not in output and all("api.x.com" not in call[0] for call in calls)


def test_live_doctor_warns_without_leaking_errors(config, monkeypatch, capsys):
    def get(url, **kwargs):
        if url.endswith("/api/"):
            return Response(status=401)
        raise requests.ConnectionError("dummy-secret")

    monkeypatch.setattr(cli, "load_config", lambda **kw: config)
    monkeypatch.setattr("rl_analyzer.diagnostics.requests.get", get)
    assert cli.main(["doctor", "--live"]) == 0
    output = capsys.readouterr().out
    assert "authentication failed" in output and "Ollama unavailable" in output
    assert "dummy-secret" not in output


def test_clipboard_failure_warning_contains_no_exception(config, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_config", lambda **kw: replace(config, clipboard_enabled=True))
    monkeypatch.setattr("rl_analyzer.diagnostics.pyperclip.paste", Mock(side_effect=OSError("dummy-secret")))
    assert cli.main(["doctor", "--offline"]) == 0
    output = capsys.readouterr().out
    assert "Clipboard unavailable" in output and "dummy-secret" not in output
