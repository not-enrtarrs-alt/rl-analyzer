"""Load and validate configuration without exposing credential values."""

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values

from .models import Player

ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = {"steam", "epic", "ps4", "xbox", "switch"}


class ConfigError(ValueError):
    """Configuration is invalid or incomplete; message contains no secrets."""


def normalize_player_id(value: str) -> str:
    """Convert a platform ID or ballchasing profile URL to a canonical ID."""
    value = value.strip()
    if "://" in value:
        try:
            url = urlsplit(value)
            hostname = url.hostname
        except ValueError:
            raise ConfigError("Invalid ballchasing profile URL") from None
        parts = url.path.strip("/").split("/")
        if (url.scheme.lower() != "https" or hostname not in {"ballchasing.com", "www.ballchasing.com"}
                or len(parts) != 3 or parts[0] != "player" or url.query or url.fragment):
            raise ConfigError("Invalid ballchasing profile URL")
        platform, identifier = parts[1], unquote(parts[2])
    else:
        if value.count(":") != 1:
            raise ConfigError("Player ID must be platform:id or a ballchasing profile URL")
        platform, identifier = value.split(":", 1)
    platform = platform.lower()
    platform = "ps4" if platform == "psn" else platform
    if platform not in PLATFORMS or not identifier or not re.fullmatch(r"[A-Za-z0-9_.-]+", identifier):
        raise ConfigError("Invalid player platform or identifier")
    if platform == "steam" and not identifier.isascii():
        raise ConfigError("Steam ID must contain digits only")
    if platform == "steam" and not identifier.isdigit():
        raise ConfigError("Steam ID must contain digits only")
    return f"{platform}:{identifier if platform == 'steam' else identifier.lower()}"


@dataclass(frozen=True)
class Config:
    """Validated runtime settings. Secret fields are excluded from repr."""

    players: tuple[Player, ...]
    ballchasing_token: str = field(repr=False)
    ballchasing_base_url: str
    max_replay_age_hours: float
    allowed_playlists: tuple[str, ...]
    max_candidates_to_inspect: int
    ballchasing_min_interval_seconds: float
    request_timeout_seconds: float
    ai_provider: str
    ai_temperature: float
    ai_max_output_tokens: int
    ollama_base_url: str
    ollama_model: str
    openai_api_key: str = field(repr=False)
    openai_base_url: str
    openai_model: str
    anthropic_api_key: str = field(repr=False)
    anthropic_base_url: str
    anthropic_model: str
    gemini_api_key: str = field(repr=False)
    gemini_base_url: str
    gemini_model: str
    tweet_language: str
    tweet_hashtag: str
    tweet_max_weighted_len: int
    tweet_target_max_chars: int
    tweet_allow_emoji: bool
    post_to_x: bool
    x_auth_mode: str
    x_api_base_url: str
    x_api_key: str = field(repr=False)
    x_api_secret: str = field(repr=False)
    x_access_token: str = field(repr=False)
    x_access_secret: str = field(repr=False)
    x_oauth2_user_token: str = field(repr=False)
    cooldown_hours: float
    manual_output_dir: Path
    clipboard_enabled: bool
    database_path: Path
    log_dir: Path
    log_level: str
    warnings: tuple[str, ...] = ()


def load_config(*, root: Path = ROOT, env: Mapping[str, str] | None = None,
                allow_incomplete: bool = False) -> Config:
    """Load root .env and environment overrides; optionally warn on missing inputs."""
    source = {k: v for k, v in dotenv_values(root / ".env").items() if v is not None}
    source.update(os.environ if env is None else env)
    warnings: list[str] = []

    def text(name: str, default: str = "") -> str:
        return source.get(name, default).strip()

    def missing(name: str) -> None:
        message = f"Missing {name}"
        if not allow_incomplete:
            raise ConfigError(message)
        warnings.append(message)

    def positive(name: str, default: str, kind: type = float) -> float | int:
        try:
            value = kind(text(name, default))
        except ValueError:
            raise ConfigError(f"{name} must be a positive number") from None
        if not math.isfinite(value) or value <= 0:
            raise ConfigError(f"{name} must be a positive number")
        return value

    def boolean(name: str, default: str) -> bool:
        value = text(name, default).lower()
        if value not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
            raise ConfigError(f"{name} must be true or false")
        return value in {"true", "1", "yes", "on"}

    def path(name: str, default: str) -> Path:
        value = Path(text(name, default))
        return value if value.is_absolute() else root / value

    players: list[Player] = []
    for i in range(1, 4):
        player_id, alias = text(f"PLAYER_{i}_ID"), text(f"PLAYER_{i}_ALIAS")
        if not player_id:
            missing(f"PLAYER_{i}_ID")
        if not alias:
            missing(f"PLAYER_{i}_ALIAS")
        if player_id:
            players.append(Player(normalize_player_id(player_id), alias))
    if len({player.id for player in players}) != len(players):
        raise ConfigError("Player IDs must be unique")

    provider = text("AI_PROVIDER", "ollama").lower()
    if provider not in {"ollama", "openai", "anthropic", "gemini", "mock"}:
        raise ConfigError("Unknown AI_PROVIDER")
    post_to_x = boolean("POST_TO_X", "false")
    auth_mode = text("X_AUTH_MODE", "oauth1").lower()
    if auth_mode not in {"oauth1", "oauth2"}:
        raise ConfigError("X_AUTH_MODE must be oauth1 or oauth2")
    required = ["BALLCHASING_TOKEN"]
    if provider in {"openai", "anthropic", "gemini"}:
        required.append(f"{provider.upper()}_API_KEY")
    if post_to_x:
        required.extend(["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"]
                        if auth_mode == "oauth1" else ["X_OAUTH2_USER_TOKEN"])
    for name in required:
        if not text(name):
            missing(name)

    hashtag = text("TWEET_HASHTAG", "#RocketLeague")
    if hashtag and not re.fullmatch(r"#[\w]+", hashtag):
        raise ConfigError("TWEET_HASHTAG must be a single hashtag or empty")
    if text("TWEET_LANGUAGE", "en").lower() != "en":
        raise ConfigError("TWEET_LANGUAGE must be en")
    length = int(positive("TWEET_MAX_WEIGHTED_LEN", "280", int))
    if length > 280:
        raise ConfigError("TWEET_MAX_WEIGHTED_LEN must not exceed 280")
    playlists = tuple(p.strip() for p in text("ALLOWED_PLAYLISTS", "ranked-standard,unranked-standard,private,tournament").split(",") if p.strip())
    if not playlists:
        raise ConfigError("ALLOWED_PLAYLISTS must not be empty")
    try:
        temperature = float(text("AI_TEMPERATURE", "0.8"))
        interval = float(text("BALLCHASING_MIN_INTERVAL_SECONDS", "0.6"))
    except ValueError:
        raise ConfigError("AI_TEMPERATURE and BALLCHASING_MIN_INTERVAL_SECONDS must be numbers") from None
    if not math.isfinite(temperature) or temperature < 0 or not math.isfinite(interval) or interval < 0.5:
        raise ConfigError("AI_TEMPERATURE must be nonnegative; BALLCHASING_MIN_INTERVAL_SECONDS must be at least 0.5")

    return Config(
        players=tuple(players), ballchasing_token=text("BALLCHASING_TOKEN"),
        ballchasing_base_url=text("BALLCHASING_BASE_URL", "https://ballchasing.com/api"),
        max_replay_age_hours=positive("MAX_REPLAY_AGE_HOURS", "48"), allowed_playlists=playlists,
        max_candidates_to_inspect=int(positive("MAX_CANDIDATES_TO_INSPECT", "10", int)),
        ballchasing_min_interval_seconds=interval, request_timeout_seconds=positive("REQUEST_TIMEOUT_SECONDS", "30"),
        ai_provider=provider, ai_temperature=temperature, ai_max_output_tokens=int(positive("AI_MAX_OUTPUT_TOKENS", "160", int)),
        ollama_base_url=text("OLLAMA_BASE_URL", "http://localhost:11434"), ollama_model=text("OLLAMA_MODEL", "llama3.1:8b"),
        openai_api_key=text("OPENAI_API_KEY"), openai_base_url=text("OPENAI_BASE_URL", "https://api.openai.com/v1"), openai_model=text("OPENAI_MODEL", "gpt-4o-mini"),
        anthropic_api_key=text("ANTHROPIC_API_KEY"), anthropic_base_url=text("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"), anthropic_model=text("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
        gemini_api_key=text("GEMINI_API_KEY"), gemini_base_url=text("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"), gemini_model=text("GEMINI_MODEL", "gemini-2.0-flash"),
        tweet_language=text("TWEET_LANGUAGE", "en"), tweet_hashtag=hashtag, tweet_max_weighted_len=length,
        tweet_target_max_chars=int(positive("TWEET_TARGET_MAX_CHARS", "240", int)), tweet_allow_emoji=boolean("TWEET_ALLOW_EMOJI", "true"),
        post_to_x=post_to_x, x_auth_mode=auth_mode, x_api_base_url=text("X_API_BASE_URL", "https://api.x.com"),
        x_api_key=text("X_API_KEY"), x_api_secret=text("X_API_SECRET"), x_access_token=text("X_ACCESS_TOKEN"),
        x_access_secret=text("X_ACCESS_SECRET"), x_oauth2_user_token=text("X_OAUTH2_USER_TOKEN"),
        cooldown_hours=positive("COOLDOWN_HOURS", "20"), manual_output_dir=path("MANUAL_OUTPUT_DIR", "out"),
        clipboard_enabled=boolean("CLIPBOARD_ENABLED", "true"), database_path=path("DATABASE_PATH", "data/rl_analyzer.sqlite3"),
        log_dir=path("LOG_DIR", "logs"), log_level=text("LOG_LEVEL", "INFO").upper(), warnings=tuple(warnings),
    )
