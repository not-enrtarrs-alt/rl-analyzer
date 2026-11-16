"""Sanitize and validate a single text-only tweet before delivery."""

from __future__ import annotations

import re
from typing import Any, Sequence, TYPE_CHECKING
import unicodedata

if TYPE_CHECKING:
    from .ai.base import AIProvider
    from .config import Config


class TweetError(ValueError):
    """Generated text does not satisfy the safety and content rules."""


_URL = re.compile(
    r"(?i)(?:[a-z][a-z0-9+.-]{1,31}://|mailto:|www\.)[^\s<>'\"`]+"
    r"|(?<![\w@])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?:/[^\s<>'\"`]*)?"
    r"|(?<![\w@])(?:[^\W_](?:[\w-]*[^\W_])?[.。．｡])+(?:xn--[a-z0-9-]{2,59}|[^\W\d_]{2,63})(?::\d+)?(?:/[^\s<>'\"`]*)?"
)
_EMAIL = re.compile(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,63}\b")
_MENTION = re.compile(r"@[\w]+")
_HASHTAG = re.compile(r"#[\w]*")
_REFUSAL = re.compile(r"(?i)^\s*(?:i\s+(?:can(?:not|'t|’t)|am\s+sorry)|i['’]m\s+sorry)\b")
_PREAMBLE = re.compile(r"(?i)^(?:tweet|here(?:'s|’s| is)\s+(?:your|the)\s+tweet)\s*:\s*")


def _is_emoji(char: str) -> bool:
    code = ord(char)
    return unicodedata.category(char) == "So" or 0x1F000 <= code <= 0x1FAFF


def _weight_text(text: str) -> int:
    return sum(2 if _is_emoji(char) or unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


def weighted_length(text: str) -> int:
    """Conservatively count CJK/emoji as two and URL spans as 23."""
    total, previous = 0, 0
    for match in _URL.finditer(text):
        total += _weight_text(text[previous:match.start()]) + 23
        previous = match.end()
    return total + _weight_text(text[previous:])


def _remove_url(match: re.Match[str]) -> str:
    token = match.group()
    stripped = token.rstrip(".,!?;:)]}")
    return token[len(stripped):]


def sanitize_tweet(raw: str, *, allow_emoji: bool = True) -> str:
    """Remove wrappers, links, mentions, hashtags and duplicate final punctuation."""
    if not isinstance(raw, str):
        raise TweetError("Tweet text is missing")
    text = raw.strip()
    text = re.sub(r"(?i)^```(?:[a-z0-9_+-]+)?[ \t]*(?:\r?\n|$)", "", text)
    text = re.sub(r"```\s*$", "", text).strip()
    text = text.strip(" \t\r\n\"'`“”‘’")
    text = _PREAMBLE.sub("", text).strip().strip(" \t\r\n\"'`“”‘’")
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = _URL.sub(_remove_url, text)
    text = _EMAIL.sub("", text)
    text = _MENTION.sub("", text).replace("@", "")
    text = _HASHTAG.sub("", text)
    text = text.replace("`", "").replace("*", "")
    if not allow_emoji:
        text = "".join(char for char in text if not _is_emoji(char) and char not in {"\ufe0f", "\u200d"})
    text = " ".join(text.split()).strip(" \"'`“”‘’")
    return re.sub(r"([.!?])[.!?]+$", r"\1", text).strip()


def validate_delivery_text(text: str, *, hashtag: str, max_weighted_len: int,
                           allow_emoji: bool) -> None:
    """Recheck text-only safety without modifying a cached or posted tweet."""
    if not isinstance(text, str) or len(text) < 20 or text != " ".join(text.split()):
        raise TweetError("Tweet is empty, too short or contains invalid whitespace")
    if _REFUSAL.match(text) or _URL.search(text) or _EMAIL.search(text) or "@" in text or "`" in text or "*" in text:
        raise TweetError("Tweet contains forbidden content")
    if hashtag and not re.fullmatch(r"#[\w]+", hashtag):
        raise TweetError("Invalid configured hashtag")
    tags = _HASHTAG.findall(text)
    if tags != ([hashtag] if hashtag else []) or (hashtag and not text.endswith(" " + hashtag)):
        raise TweetError("Tweet has invalid hashtags")
    if not allow_emoji and any(_is_emoji(char) for char in text):
        raise TweetError("Tweet contains disabled emoji")
    if (not isinstance(max_weighted_len, int) or isinstance(max_weighted_len, bool)
            or not 0 < max_weighted_len <= 280 or weighted_length(text) > max_weighted_len):
        raise TweetError("Tweet exceeds the weighted length limit")


def finalize_tweet(raw: str, *, score: tuple[int, int], names: Sequence[str],
                   hashtag: str = "#RocketLeague", max_weighted_len: int = 280,
                   allow_emoji: bool = True) -> str:
    """Return a validated tweet, or raise TweetError without generating a fallback."""
    if hashtag and not re.fullmatch(r"#[\w]+", hashtag):
        raise TweetError("Invalid configured hashtag")
    if not isinstance(max_weighted_len, int) or isinstance(max_weighted_len, bool) or not 0 < max_weighted_len <= 280:
        raise TweetError("Invalid weighted length limit")
    if (not isinstance(score, (tuple, list)) or len(score) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in score)):
        raise TweetError("Invalid match score")
    text = sanitize_tweet(raw, allow_emoji=allow_emoji)
    if not text or len(text) < 20:
        raise TweetError("Tweet is empty or too short")
    if _REFUSAL.match(text):
        raise TweetError("Tweet is a refusal")
    expected = f"{score[0]}-{score[1]}"
    if not re.search(rf"(?<!\d){re.escape(expected)}(?!\d)", text):
        raise TweetError("Tweet does not include the match score")
    if not any(re.search(rf"(?<!\w){re.escape(name.strip())}(?!\w)", text, re.IGNORECASE)
               for name in names if isinstance(name, str) and name.strip()):
        raise TweetError("Tweet does not include a player name")
    final = f"{text} {hashtag}" if hashtag else text
    if weighted_length(final) > max_weighted_len:
        raise TweetError("Tweet exceeds the weighted length limit")
    validate_delivery_text(final, hashtag=hashtag, max_weighted_len=max_weighted_len, allow_emoji=allow_emoji)
    return final


def generate_tweet(provider: AIProvider, payload: dict[str, Any], config: Config) -> str:
    """Generate and finalize a tweet, retrying invalid text once without a fallback."""
    from .ai.base import AIError, AIValidationError
    from .ai.prompt import build_prompts

    try:
        score_data = payload["match"]["score"]
        score = (score_data["trio"], score_data["opponents"])
        players = payload["players"]
        if not isinstance(players, list) or any(not isinstance(player, dict) for player in players):
            raise ValueError
        names = [name for player in players for name in (player.get("alias"), player.get("in_game_name"))
                 if isinstance(name, str) and name.strip()]
        if (not names or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in score)):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise AIError("Invalid stats payload") from None
    for attempt in range(2):
        try:
            system, user = build_prompts(payload, config, shorten=bool(attempt))
        except (TypeError, ValueError):
            raise AIError("Invalid stats payload") from None
        raw = provider.generate(system, user)
        try:
            return finalize_tweet(raw, score=score, names=names, hashtag=config.tweet_hashtag,
                                  max_weighted_len=config.tweet_max_weighted_len,
                                  allow_emoji=config.tweet_allow_emoji)
        except TweetError as error:
            if attempt:
                reasons = {
                    "Tweet is empty or too short": "empty_or_short", "Tweet is a refusal": "refusal",
                    "Tweet does not include the match score": "score", "Tweet does not include a player name": "player_name",
                    "Tweet exceeds the weighted length limit": "length",
                }
                raise AIValidationError(reasons.get(str(error), "format")) from None
    raise AssertionError("unreachable")
