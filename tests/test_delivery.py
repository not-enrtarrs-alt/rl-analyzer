"""Delivery files and clipboard behavior use isolated temporary paths."""

from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest

from rl_analyzer.delivery import DeliveryError, DeliveryMetadata, deliver_tweet

NOW = datetime(2026, 10, 30, 19, tzinfo=timezone.utc)


@pytest.fixture
def metadata():
    return DeliveryMetadata("replay-1", "match-1", "2026-10-30T18:04:00Z", "win",
                            {"trio": 3, "opponents": 2}, "mock", None, "manual")


def test_manual_delivery_writes_utf8_metadata_history_and_clipboard(tmp_path, metadata, monkeypatch, capsys):
    copy = Mock()
    monkeypatch.setattr("rl_analyzer.delivery.pyperclip.copy", copy)
    text = "Ali won 3-2 with 2 demos ⚽ #RocketLeague"
    deliver_tweet(text, metadata, tmp_path, now=NOW)
    assert (tmp_path / "tweet.txt").read_bytes() == text.encode("utf-8")
    data = json.loads((tmp_path / "last_run.json").read_text(encoding="utf-8"))
    assert data == {"replay_id": "replay-1", "match_key": "match-1", "match_url": "https://ballchasing.com/replay/replay-1", "match_date": "2026-10-30T18:04:00Z", "result": "win", "score": {"trio": 3, "opponents": 2}, "provider": "mock", "model": None, "status": "manual", "tweet_id": None, "delivered_at_utc": "2026-10-30T19:00:00.000000Z"}
    assert [p.read_text(encoding="utf-8") for p in (tmp_path / "history").glob("*.txt")] == [text]
    copy.assert_called_once_with(text)
    assert text in capsys.readouterr().out


def test_posted_archive_and_no_clipboard(tmp_path, metadata, monkeypatch):
    copy = Mock()
    monkeypatch.setattr("rl_analyzer.delivery.pyperclip.copy", copy)
    deliver_tweet("text", metadata, tmp_path, clipboard_enabled=False, posted=True, now=NOW)
    assert [p.read_text(encoding="utf-8") for p in (tmp_path / "posted").glob("*.txt")] == ["text"]
    copy.assert_not_called()


def test_clipboard_failure_is_nonfatal(tmp_path, metadata, monkeypatch, caplog):
    monkeypatch.setattr("rl_analyzer.delivery.pyperclip.copy", Mock(side_effect=RuntimeError("secret")))
    with caplog.at_level("WARNING", logger="rl_analyzer"):
        deliver_tweet("text", metadata, tmp_path, now=NOW)
    assert "Clipboard unavailable" in caplog.text and "secret" not in caplog.text
    assert (tmp_path / "tweet.txt").read_text(encoding="utf-8") == "text"


def test_demo_writes_separate_file_and_unique_history(tmp_path, metadata):
    for _ in range(2):
        deliver_tweet("demo", metadata, tmp_path, clipboard_enabled=False, demo=True, now=NOW)
    assert (tmp_path / "demo_tweet.txt").read_text(encoding="utf-8") == "demo"
    assert len(list((tmp_path / "history").glob("*.txt"))) == 2
    assert not (tmp_path / "tweet.txt").exists()


def test_file_error_fails_safely(tmp_path, metadata):
    target = tmp_path / "not-a-directory"
    target.write_text("existing", encoding="utf-8")
    with pytest.raises(DeliveryError, match="Could not write"):
        deliver_tweet("text", metadata, target, clipboard_enabled=False, now=NOW)
    assert target.read_text(encoding="utf-8") == "existing"
