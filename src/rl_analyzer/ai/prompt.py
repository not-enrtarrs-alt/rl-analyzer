"""Build a constrained prompt from the extracted, opponent-free payload."""

import json
from typing import Any

from ..config import Config


def build_prompts(payload: dict[str, Any], config: Config, *, shorten: bool = False) -> tuple[str, str]:
    """Return system and user messages; missing statistics must not be invented."""
    target = min(config.tweet_target_max_chars, config.tweet_max_weighted_len)
    emoji_instruction = "Use at most 2 emoji; emoji count as 2." if config.tweet_allow_emoji else "Do not use emoji."
    system = (
        "You write ONE tweet in English recapping a Rocket League match for a private friend group. "
        "Voice: funny recap with light, playful trash talk. Use only the stats in the JSON. "
        "Never invent numbers or mention null/missing stats. Mention the result and score. "
        "Name the standout player and roast one underperformer using the exact provided aliases. "
        "Include at least one boost or demo stat when one is available. "
        f"Keep it under {target} weighted characters. {emoji_instruction} "
        "Do not use hashtags, @mentions, URLs, line breaks, quotes, or markdown. "
        "Do not name opponents. Do not write anything except the tweet text."
    )
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    score = payload.get("match", {}).get("score", {})
    trio, opponents = score.get("trio"), score.get("opponents")
    if (isinstance(trio, int) and not isinstance(trio, bool)
            and isinstance(opponents, int) and not isinstance(opponents, bool)):
        instruction = f"Write the tweet now. Use the exact score {trio}-{opponents} (trio first, ASCII hyphen)."
    else:
        instruction = "Write the tweet now."
    if shorten:
        instruction += " Your previous answer was invalid; write a shorter tweet with the exact score and a player alias."
    return system, f"{data}\n\n{instruction}"
