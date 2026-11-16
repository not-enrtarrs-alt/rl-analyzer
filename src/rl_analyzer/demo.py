"""Offline end-to-end demo using the bundled synthetic replay."""

from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone

from .ai import create_provider
from .ai.base import AIError
from .config import ROOT, ConfigError, load_config
from .delivery import DeliveryError, DeliveryMetadata, deliver_tweet
from .select import match_key
from .stats import InvalidReplay, extract_stats
from .tweet import generate_tweet

logger = logging.getLogger("rl_analyzer")


def run_demo(*, output_dir: Path | None = None, fixture_path: Path | None = None) -> int:
    """Exercise extraction, mock generation, validation and local delivery only."""
    fixture_path = fixture_path or ROOT / "tests" / "fixtures" / "replay_detail.json"
    output_dir = output_dir or ROOT / "out"
    env = {
        "BALLCHASING_TOKEN": "demo-placeholder",
        "PLAYER_1_ID": "steam:123", "PLAYER_1_ALIAS": "Ali",
        "PLAYER_2_ID": "epic:abc", "PLAYER_2_ALIAS": "Bea",
        "PLAYER_3_ID": "ps4:example", "PLAYER_3_ALIAS": "Cam",
        "AI_PROVIDER": "mock", "POST_TO_X": "false",
        "CLIPBOARD_ENABLED": os.environ.get("CLIPBOARD_ENABLED", "true"),
    }
    try:
        with tempfile.TemporaryDirectory(prefix="rl-analyzer-demo-") as isolated:
            config = replace(load_config(root=Path(isolated), env=env), manual_output_dir=output_dir)
            replay = json.loads(fixture_path.read_text(encoding="utf-8"))
            payload = extract_stats(replay, config.players)
            text = generate_tweet(create_provider(config), payload, config)
            match = payload["match"]
            metadata = DeliveryMetadata(replay["id"], match_key(replay), match["date_utc"],
                                        match["result"], match["score"], "mock", None, "demo")
            deliver_tweet(text, metadata, output_dir, clipboard_enabled=config.clipboard_enabled,
                          demo=True, now=datetime.now(timezone.utc))
        return 0
    except (OSError, ValueError, KeyError, ConfigError, InvalidReplay, AIError, DeliveryError):
        logger.error("Offline demo failed; inspect fixture and output directory")
        return 6
