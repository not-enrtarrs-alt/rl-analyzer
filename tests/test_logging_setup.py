"""Logging writes messages to a UTF-8 file without duplicate handlers."""

import pytest

from rl_analyzer.logging_setup import setup_logging


def test_logging_to_file_and_reconfigure(tmp_path) -> None:
    logger = setup_logging(tmp_path)
    logger.info("hello")
    setup_logging(tmp_path).info("again")
    assert (tmp_path / "rl_analyzer.log").read_text(encoding="utf-8").count("again") == 1
    assert "hello" in (tmp_path / "rl_analyzer.log").read_text(encoding="utf-8")
    assert "Z INFO hello" in (tmp_path / "rl_analyzer.log").read_text(encoding="utf-8")


def test_invalid_log_level(tmp_path) -> None:
    with pytest.raises(ValueError, match="LOG_LEVEL"):
        setup_logging(tmp_path, "invalid")
