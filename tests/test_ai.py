"""AI prompting and providers are tested without network or credentials."""

import json
from dataclasses import replace

import pytest

from rl_analyzer.ai import create_provider, provider_model
from rl_analyzer.ai.base import AIError, AIProvider
from rl_analyzer.ai.anthropic import AnthropicProvider
from rl_analyzer.ai.gemini import GeminiProvider
from rl_analyzer.ai.ollama import OllamaProvider
from rl_analyzer.ai.openai import OpenAIProvider
from rl_analyzer.ai.prompt import build_prompts
from rl_analyzer.stats import extract_stats


def test_provider_interface_is_abstract():
    with pytest.raises(TypeError):
        AIProvider()


def test_prompt_contains_real_payload_and_constraints(config, replay):
    payload = extract_stats(replay, config.players)
    system, user = build_prompts(payload, config)
    assert json.loads(user.split("\n\n", 1)[0]) == payload
    assert "funny" in system and "trash talk" in system
    assert "standout" in system and "underperformer" in system
    assert "result and score" in system and "boost or demo" in system
    assert "null/missing" in system and "Never invent" in system
    assert "240 weighted characters" in system and "at most 2 emoji" in system
    assert "hashtags" in system and "@mentions" in system and "URLs" in system
    assert "Opponent" not in user
    assert "exact score 3-2 (trio first, ASCII hyphen)" in user
    assert "exact provided aliases" in system


def test_prompt_respects_limits_emoji_and_shorten(config, replay):
    config = replace(config, tweet_allow_emoji=False, tweet_target_max_chars=120)
    system, user = build_prompts(extract_stats(replay, config.players), config, shorten=True)
    assert "under 120 weighted characters" in system
    assert "Do not use emoji" in system
    assert "shorter tweet" in user and "exact score" in user


class CaptureHTTP:
    def __init__(self, body):
        self.body, self.calls = body, []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.body


def test_ollama_request_and_response(config):
    http = CaptureHTTP({"message": {"content": "tweet text"}})
    assert OllamaProvider(config, http=http).generate("system", "user") == "tweet text"
    url, request = http.calls[0]
    assert url == "http://localhost:11434/api/chat"
    assert request["body"] == {"model": config.ollama_model, "messages": [{"role": "system", "content": "system"}, {"role": "user", "content": "user"}], "stream": False, "options": {"temperature": config.ai_temperature, "num_predict": config.ai_max_output_tokens}}


@pytest.mark.parametrize("body", [{}, {"message": {}}, {"message": {"content": "  "}}])
def test_ollama_missing_text_is_an_ai_error(config, body):
    with pytest.raises(AIError, match="no text"):
        OllamaProvider(config, http=CaptureHTTP(body)).generate("system", "user")


def test_openai_request_and_response(config):
    config = replace(config, openai_api_key="dummy-openai-key", openai_base_url="https://example.invalid/v1")
    http = CaptureHTTP({"choices": [{"message": {"content": "tweet text"}}]})
    assert OpenAIProvider(config, http=http).generate("system", "user") == "tweet text"
    url, request = http.calls[0]
    assert url == "https://example.invalid/v1/chat/completions"
    assert request["headers"] == {"Authorization": "Bearer dummy-openai-key"}
    assert request["body"] == {"model": config.openai_model, "messages": [{"role": "system", "content": "system"}, {"role": "user", "content": "user"}], "temperature": config.ai_temperature, "max_tokens": config.ai_max_output_tokens}


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]}])
def test_openai_missing_text_is_an_ai_error(config, body):
    with pytest.raises(AIError, match="no text"):
        OpenAIProvider(config, http=CaptureHTTP(body)).generate("system", "user")


def test_anthropic_request_and_response(config):
    config = replace(config, anthropic_api_key="dummy-anthropic-key", anthropic_base_url="https://example.invalid/v1")
    http = CaptureHTTP({"content": [{"type": "text", "text": "tweet text"}]})
    assert AnthropicProvider(config, http=http).generate("system", "user") == "tweet text"
    url, request = http.calls[0]
    assert url == "https://example.invalid/v1/messages"
    assert request["headers"] == {"x-api-key": "dummy-anthropic-key", "anthropic-version": "2023-06-01"}
    assert request["body"] == {"model": config.anthropic_model, "system": "system", "messages": [{"role": "user", "content": "user"}], "temperature": config.ai_temperature, "max_tokens": config.ai_max_output_tokens}


@pytest.mark.parametrize("body", [{}, {"content": []}, {"content": [{"type": "thinking", "text": "not tweet"}]}])
def test_anthropic_missing_text_is_an_ai_error(config, body):
    with pytest.raises(AIError, match="no text"):
        AnthropicProvider(config, http=CaptureHTTP(body)).generate("system", "user")


def test_gemini_request_and_response(config):
    config = replace(config, gemini_api_key="dummy-gemini-key", gemini_base_url="https://example.invalid/v1beta")
    http = CaptureHTTP({"candidates": [{"content": {"parts": [{"text": "private thought", "thought": True}, {"text": "tweet text"}]}}]})
    assert GeminiProvider(config, http=http).generate("system", "user") == "tweet text"
    url, request = http.calls[0]
    assert url == f"https://example.invalid/v1beta/models/{config.gemini_model}:generateContent"
    assert request["params"] == {"key": "dummy-gemini-key"}
    assert request["body"] == {"systemInstruction": {"parts": [{"text": "system"}]}, "contents": [{"role": "user", "parts": [{"text": "user"}]}], "generationConfig": {"temperature": config.ai_temperature, "maxOutputTokens": config.ai_max_output_tokens}}


@pytest.mark.parametrize("body", [{}, {"candidates": []}, {"candidates": [{"content": {"parts": [{"text": "secret", "thought": True}]}}]}])
def test_gemini_missing_text_is_an_ai_error(config, body):
    with pytest.raises(AIError, match="no text"):
        GeminiProvider(config, http=CaptureHTTP(body)).generate("system", "user")


def test_mock_uses_payload_and_is_deterministic(config, replay):
    payload = extract_stats(replay, config.players)
    system, user = build_prompts(payload, config)
    provider = create_provider(config)
    tweet = provider.generate(system, user)
    assert tweet == provider.generate(system, user)
    assert all(part in tweet for part in ("win", "3-2", "Ali", "Cam", "2 demos"))
    assert "#" not in tweet and "Opponent" not in tweet
    assert provider_model(config) is None


def test_mock_handles_missing_stats_without_inventing(config, replay):
    payload = extract_stats(replay, config.players)
    for player in payload["players"]:
        for key in ("demos_inflicted", "demos_taken", "boost_bpm", "avg_boost", "time_zero_boost_seconds"):
            player[key] = None
    system, user = build_prompts(payload, config)
    result = create_provider(config).generate(system, user)
    assert "3-2" in result and "demos" not in result and "boost" not in result


def test_mock_invalid_payload_fails_without_fallback(config):
    with pytest.raises(AIError, match="invalid stats"):
        create_provider(config).generate("system", "{}")


def test_mock_rejects_inconsistent_player_markers(config, replay):
    payload = extract_stats(replay, config.players)
    payload["players"][1]["standout"] = True
    _, user = build_prompts(payload, config)
    with pytest.raises(AIError, match="invalid stats"):
        create_provider(config).generate("system", user)


@pytest.mark.parametrize(("name", "cls"), [("ollama", OllamaProvider), ("openai", OpenAIProvider), ("anthropic", AnthropicProvider), ("gemini", GeminiProvider)])
def test_factory_respects_selection_and_credentials(config, name, cls):
    changes = {"ai_provider": name}
    if name != "ollama":
        changes[f"{name}_api_key"] = "dummy"
    configured = replace(config, **changes)
    assert isinstance(create_provider(configured, http=CaptureHTTP({})), cls)
    assert provider_model(configured)
    if name != "ollama":
        with pytest.raises(AIError, match="API_KEY"):
            create_provider(replace(configured, **{f"{name}_api_key": ""}))


def test_unknown_provider_never_falls_back(config):
    with pytest.raises(AIError, match="Unknown"):
        create_provider(replace(config, ai_provider="unknown"))
