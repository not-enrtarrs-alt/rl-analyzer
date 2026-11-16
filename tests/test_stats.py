"""Replay statistics are extracted without invented values."""

import copy
import logging

import pytest

from rl_analyzer.models import Player
from rl_analyzer.stats import InvalidReplay, extract_stats


def test_extracts_result_players_and_team_totals(replay, config):
    payload = extract_stats(replay, config.players)
    assert payload["match"] == {"date_utc": "2026-10-30T18:04:00Z", "playlist": "Ranked Standard", "map": "DFH Stadium", "duration_seconds": 312, "overtime": False, "result": "win", "score": {"trio": 3, "opponents": 2}}
    assert [p["alias"] for p in payload["players"]] == ["Ali", "Bea", "Cam"]
    assert payload["players"][0] == {"alias": "Ali", "in_game_name": "Alias A", "goals": 2, "assists": 1, "saves": 3, "shots": 5, "score": 520, "shooting_pct": 40.0, "demos_inflicted": 2, "demos_taken": 1, "boost_bpm": 410, "avg_boost": 48.2, "time_zero_boost_seconds": 35.4, "mvp": True, "standout": True}
    assert payload["players"][-1]["underperformer"] is True
    assert sum(p.get("standout", False) for p in payload["players"]) == 1
    assert sum(p.get("underperformer", False) for p in payload["players"]) == 1
    assert payload["team_totals"] == {"goals": 3, "assists": 2, "saves": 7, "shots": 12, "score": 1100, "demos_inflicted": 5, "demos_taken": 3, "boost_bpm": 1200, "avg_boost": 145.0, "time_zero_boost_seconds": 90.2}
    assert "Opponent" not in str(payload)


def test_orange_team_and_loss(replay, config):
    replay["blue"], replay["orange"] = replay["orange"], replay["blue"]
    replay["blue"]["goals"] = 4
    payload = extract_stats(replay, config.players)
    assert payload["match"]["result"] == "loss"
    assert payload["match"]["score"] == {"trio": 3, "opponents": 4}


def test_draw_and_score_falls_back_to_team_core(replay, config):
    del replay["blue"]["goals"]
    replay["orange"]["goals"] = 3
    assert extract_stats(replay, config.players)["match"]["result"] == "draw"


def test_missing_optional_stats_are_null_not_estimated(replay, config):
    del replay["blue"]["players"][0]["stats"]["core"]["assists"]
    del replay["blue"]["players"][0]["stats"]["boost"]
    del replay["blue"]["stats"]
    payload = extract_stats(replay, config.players)
    assert payload["players"][0]["assists"] is None
    assert payload["players"][0]["boost_bpm"] is None
    assert all(value is None for value in payload["team_totals"].values())


def test_impact_ties_float_rounding_and_alias_fallback(replay, config):
    roster = replay["blue"]["players"]
    for player in roster:
        player["stats"]["core"]["score"] = 100
    roster[0]["stats"]["core"].update(goals=1, saves=2)
    roster[1]["stats"]["core"].update(goals=1, saves=3)
    roster[2]["stats"]["core"].update(goals=0, saves=5)
    roster[1]["stats"]["boost"]["avg_amount"] = 42.26
    players = (config.players[0], Player(config.players[1].id, ""), config.players[2])
    result = extract_stats(replay, players)["players"]
    assert [p["alias"] for p in result] == ["Alias B", "Ali", "Cam"]
    assert result[0]["avg_boost"] == 42.3


def test_naive_dates_warn_and_offsets_are_utc(replay, config, caplog):
    replay["date"] = "2026-10-30T20:04:00+02:00"
    assert extract_stats(replay, config.players)["match"]["date_utc"] == "2026-10-30T18:04:00Z"
    replay["date"] = "2026-10-30T18:04:00"
    with caplog.at_level(logging.WARNING, logger="rl_analyzer"):
        assert extract_stats(replay, config.players)["match"]["date_utc"] == "2026-10-30T18:04:00Z"
    assert "assuming UTC" in caplog.text


@pytest.mark.parametrize("edit", [
    lambda r: r["blue"]["players"][0]["stats"]["core"].pop("score"),
    lambda r: r["blue"]["players"].pop(),
    lambda r: (r["orange"].pop("goals"), r["orange"]["stats"]["core"].pop("goals")),
    lambda r: r["orange"].update(goals=2.01),
    lambda r: r.update(date="bad"),
    lambda r: r["orange"]["players"].append(copy.deepcopy(r["blue"]["players"][0])),
])
def test_invalid_required_data_is_rejected(replay, config, edit):
    edit(replay)
    with pytest.raises(InvalidReplay):
        extract_stats(replay, config.players)
