"""CLI skeleton and offline doctor tests."""

from rl_analyzer import cli
from rl_analyzer.config import load_config


def test_offline_doctor_warns_without_credentials(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_config", lambda **kwargs: load_config(root=tmp_path, env={}, **kwargs))
    monkeypatch.setattr("rl_analyzer.diagnostics.pyperclip.paste", lambda: "")
    assert cli.main(["doctor", "--offline"]) == 0
    output = capsys.readouterr().out
    assert "WARNING: Missing BALLCHASING_TOKEN" in output
    assert "WARNING: Missing PLAYER_1_ID" in output
    assert "X posting: disabled" in output


def test_doctor_invalid_config_reports_error(tmp_path, monkeypatch, capsys) -> None:
    env = {"TWEET_HASHTAG": "bad"}
    monkeypatch.setattr(cli, "load_config", lambda **kwargs: load_config(root=tmp_path, env=env, **kwargs))
    assert cli.main(["doctor", "--offline"]) == 2
    assert "ERROR: TWEET_HASHTAG" in capsys.readouterr().out


def test_history_rejects_nonpositive_limit(capsys) -> None:
    assert cli.main(["history", "--limit", "0"]) == 2
    assert "positive" in capsys.readouterr().out


def test_run_and_preview_forward_flags(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(cli, "run_daily", lambda **kwargs: calls.append(kwargs) or 0)
    assert cli.main(["run", "--dry-run", "--force", "--verbose"]) == 0
    assert calls[-1] == {"dry_run": True, "force": True, "verbose": True}
    assert cli.main(["preview", "--replay-id", "replay-1", "--verbose"]) == 0
    assert calls[-1] == {"dry_run": True, "replay_id": "replay-1", "verbose": True}


def test_demo_command_calls_offline_demo(monkeypatch) -> None:
    monkeypatch.setattr(cli, "run_demo", lambda: 0)
    assert cli.main(["demo"]) == 0
