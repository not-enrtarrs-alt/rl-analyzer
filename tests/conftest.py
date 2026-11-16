"""Shared synthetic configuration for offline tests."""

import json
from pathlib import Path

import pytest

from rl_analyzer.config import load_config


@pytest.fixture
def config(tmp_path):
    return load_config(root=tmp_path, env={
        "BALLCHASING_TOKEN": "dummy-secret",
        "PLAYER_1_ID": "steam:123", "PLAYER_1_ALIAS": "Ali",
        "PLAYER_2_ID": "epic:abc", "PLAYER_2_ALIAS": "Bea",
        "PLAYER_3_ID": "ps4:example", "PLAYER_3_ALIAS": "Cam",
        "AI_PROVIDER": "mock", "CLIPBOARD_ENABLED": "false",
    })


@pytest.fixture
def replay():
    path = Path(__file__).parent / "fixtures" / "replay_detail.json"
    return json.loads(path.read_text(encoding="utf-8"))
