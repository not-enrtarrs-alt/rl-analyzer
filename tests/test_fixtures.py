"""Sanity checks for synthetic replay fixtures."""

import json
from pathlib import Path

from rl_analyzer.config import normalize_player_id

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_detail_and_list_fixtures(config):
    detail = load("replay_detail.json")
    ids = {normalize_player_id(f"{p['id']['platform']}:{p['id']['id']}") for p in detail["blue"]["players"]}
    assert ids == {p.id for p in config.players}
    assert detail["id"] in {item["id"] for item in load("replay_list.json")["list"]}


def test_rejection_fixtures(config):
    assert load("replay_2v2.json")["team_size"] == 2
    split = load("replay_split_team.json")
    ids = {normalize_player_id(f"{p['id']['platform']}:{p['id']['id']}") for p in split["blue"]["players"]}
    assert not {p.id for p in config.players}.issubset(ids)
