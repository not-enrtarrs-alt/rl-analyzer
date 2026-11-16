"""Configuration and player identity validation tests."""

import pytest

from rl_analyzer.config import ConfigError, load_config, normalize_player_id


@pytest.fixture
def settings() -> dict[str, str]:
    return {
        "BALLCHASING_TOKEN": "secret-token",
        "PLAYER_1_ID": "steam:123", "PLAYER_1_ALIAS": "One",
        "PLAYER_2_ID": "epic:abc", "PLAYER_2_ALIAS": "Two",
        "PLAYER_3_ID": "ps4:Name", "PLAYER_3_ALIAS": "Three",
    }


@pytest.mark.parametrize(("value", "expected"), [
    ("steam:123", "steam:123"),
    ("EPIC:ABC", "epic:abc"),
    ("PSN:Name", "ps4:name"),
    ("https://ballchasing.com/player/PSN/Name", "ps4:name"),
    ("https://ballchasing.com/player/steam/123/", "steam:123"),
])
def test_player_normalization(value: str, expected: str) -> None:
    assert normalize_player_id(value) == expected


@pytest.mark.parametrize("value", ["Player Name", "steam:", "steam:abc", "ps5:123", "epic:abc/xyz", "https://evil.com/player/steam/123", "http://ballchasing.com/player/steam/123", "https://[broken/player/steam/123"])
def test_invalid_player_id(value: str) -> None:
    with pytest.raises(ConfigError):
        normalize_player_id(value)


def test_load_defaults_and_secret_repr(tmp_path, settings) -> None:
    config = load_config(root=tmp_path, env=settings)
    assert config.players[2].id == "ps4:name"
    assert not config.post_to_x
    assert config.ai_provider == "ollama"
    assert config.ballchasing_base_url == "https://ballchasing.com/api"
    assert config.database_path == tmp_path / "data/rl_analyzer.sqlite3"
    assert "secret-token" not in repr(config)


def test_duplicates_rejected(tmp_path, settings) -> None:
    settings["PLAYER_2_ID"] = "https://ballchasing.com/player/steam/123"
    with pytest.raises(ConfigError, match="unique"):
        load_config(root=tmp_path, env=settings)


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
def test_provider_key_only_for_selected_provider(tmp_path, settings, provider) -> None:
    settings["AI_PROVIDER"] = provider
    with pytest.raises(ConfigError, match=f"{provider.upper()}_API_KEY"):
        load_config(root=tmp_path, env=settings)
    settings[f"{provider.upper()}_API_KEY"] = "secret"
    assert load_config(root=tmp_path, env=settings).ai_provider == provider


def test_x_keys_only_when_enabled(tmp_path, settings) -> None:
    load_config(root=tmp_path, env=settings)
    settings["POST_TO_X"] = "true"
    settings["X_AUTH_MODE"] = "oauth2"
    with pytest.raises(ConfigError, match="X_OAUTH2_USER_TOKEN"):
        load_config(root=tmp_path, env=settings)
    settings["X_OAUTH2_USER_TOKEN"] = "secret"
    assert load_config(root=tmp_path, env=settings).post_to_x


def test_oauth1_requires_all_credentials(tmp_path, settings) -> None:
    settings.update({"POST_TO_X": "true", "X_API_KEY": "a", "X_API_SECRET": "b", "X_ACCESS_TOKEN": "c"})
    with pytest.raises(ConfigError, match="X_ACCESS_SECRET"):
        load_config(root=tmp_path, env=settings)
    settings["X_ACCESS_SECRET"] = "secret"
    assert "secret" not in repr(load_config(root=tmp_path, env=settings))


@pytest.mark.parametrize(("name", "value"), [
    ("MAX_REPLAY_AGE_HOURS", "0"), ("COOLDOWN_HOURS", "-1"),
    ("MAX_CANDIDATES_TO_INSPECT", "0"), ("TWEET_HASHTAG", "RL"),
    ("TWEET_MAX_WEIGHTED_LEN", "281"), ("BALLCHASING_MIN_INTERVAL_SECONDS", "0.1"),
    ("PLAYER_1_ALIAS", ""), ("POST_TO_X", "maybe"), ("TWEET_HASHTAG", "#RL @handle"),
    ("TWEET_LANGUAGE", "fr"),
])
def test_invalid_settings(tmp_path, settings, name, value) -> None:
    settings[name] = value
    with pytest.raises(ConfigError):
        load_config(root=tmp_path, env=settings)


def test_incomplete_config_reports_warnings(tmp_path) -> None:
    config = load_config(root=tmp_path, env={}, allow_incomplete=True)
    assert "Missing BALLCHASING_TOKEN" in config.warnings
    assert "Missing PLAYER_1_ID" in config.warnings
    assert not config.post_to_x


def test_dotenv_loaded_and_environment_overrides(tmp_path, settings) -> None:
    (tmp_path / ".env").write_text("TWEET_HASHTAG=#Example\nCOOLDOWN_HOURS=21\n", encoding="utf-8")
    settings["COOLDOWN_HOURS"] = "22"
    config = load_config(root=tmp_path, env=settings)
    assert config.tweet_hashtag == "#Example"
    assert config.cooldown_hours == 22


def test_ballchasing_base_url_is_configurable(tmp_path, settings) -> None:
    settings["BALLCHASING_BASE_URL"] = "https://example.invalid/api"
    assert load_config(root=tmp_path, env=settings).ballchasing_base_url == "https://example.invalid/api"


def test_anthropic_and_gemini_base_urls_are_configurable(tmp_path, settings) -> None:
    settings.update(ANTHROPIC_BASE_URL="https://anthropic.invalid/v1", GEMINI_BASE_URL="https://gemini.invalid/v1beta")
    config = load_config(root=tmp_path, env=settings)
    assert config.anthropic_base_url == "https://anthropic.invalid/v1"
    assert config.gemini_base_url == "https://gemini.invalid/v1beta"
