"""Tweet rules and weighted character counting without network access."""

import pytest

from rl_analyzer.ai import create_provider
from rl_analyzer.ai.base import AIError, AIValidationError
from rl_analyzer.stats import extract_stats
from rl_analyzer.tweet import TweetError, finalize_tweet, generate_tweet, sanitize_tweet, validate_delivery_text, weighted_length


def finalize(text, **kwargs):
    return finalize_tweet(text, score=(3, 2), names=["Ali", "Bea", "Cam"], **kwargs)


def test_weighted_length_emoji_cjk_and_urls():
    assert weighted_length("a😀漢") == 5
    assert weighted_length("a https://example.com") == 25
    assert weighted_length("a www.example.com") == 25
    assert weighted_length("Ali 🚗") == 6
    assert weighted_length("🇺🇸") >= 2
    assert weighted_length("👨‍👩‍👧‍👦") >= 2


def test_markdown_urls_mentions_and_hashtags_removed():
    raw = '```text\nHere is your tweet: "Ali won 3-2 with 2 demos! https://example.com/match @someone #old #RocketLeague!!!"\n```'
    text = finalize(raw)
    assert text.endswith(" #RocketLeague")
    assert text.count("#RocketLeague") == 1
    assert "https" not in text and "@" not in text and "#old" not in text
    assert "```" not in text and '"' not in text and "!!!" not in text
    assert "Ali won 3-2 with 2 demos" in text


def test_bare_domains_emails_and_markdown_links_removed():
    text = finalize("Tweet: Ali won 3-2 with a demo! [report](https://example.com/a) www.example.com example.gg/a friend@example.com @friend")
    assert "example" not in text and "@" not in text and "[" not in text
    assert "report" in text and text.endswith("#RocketLeague")


def test_unicode_domains_and_embedded_scheme_are_removed():
    text = finalize("Ali won 3-2 with two demos! 例子.中国 and prehttps://example.com/a")
    assert "例子.中国" not in text and "https://" not in text and "example.com" not in text


def test_punycode_domain_is_removed():
    text = finalize("Ali won 3-2 with two demos. example.xn--p1ai/path")
    assert "example" not in text and "xn--p1ai" not in text


def test_ip_unicode_dot_and_other_schemes_removed():
    text = finalize("Ali won 3-2 with two demos. 192.168.1.1/game 例子。中国 steam://join/game mailto:friend@example.com")
    assert all(item not in text for item in ("192.168", "例子。中国", "steam://", "mailto:", "@"))


def test_whitespace_punctuation_and_empty_hashtag():
    text = finalize("`Ali   won 3-2\nwith 2 demos!!!!!!`", hashtag="")
    assert text == "Ali won 3-2 with 2 demos!"


@pytest.mark.parametrize("prefix", ["I can't", "I cannot", "I'm sorry", "I’m sorry"])
def test_refusals_are_rejected(prefix):
    with pytest.raises(TweetError, match="refusal"):
        finalize(f"{prefix}, Ali won 3-2 with 2 demos.")


@pytest.mark.parametrize("text", ["", "Ali 3-2", "An unnamed player scored a 3-2 victory.", "Ali won 4-2 and made two demos.", "Ali won 13-20 with two demos."])
def test_missing_content_score_or_alias_rejected(text):
    with pytest.raises(TweetError):
        finalize(text)


def test_score_and_alias_must_not_be_substrings():
    with pytest.raises(TweetError, match="player name"):
        finalize("Reality won 3-2 and made two demos.")
    with pytest.raises(TweetError, match="match score"):
        finalize("Ali won 13-20 and made two demos.")


def test_weighted_limit_includes_hashtag():
    text = "Ali won 3-2 with two demos " + "漢" * 130
    with pytest.raises(TweetError, match="weighted length"):
        finalize(text)
    assert weighted_length(finalize("Ali won 3-2 with two demos. ⚽")) <= 280


def test_emoji_disabled_removes_emoji_without_removing_cjk():
    text = finalize("Ali won 3-2 with 2 demos 漢 ⚽🚗", allow_emoji=False)
    assert "漢" in text and "⚽" not in text and "🚗" not in text


def test_extra_emoji_do_not_cause_failure():
    assert "🚗" in finalize("Ali won 3-2 with 2 demos ⚽🚗😀")


def test_hashtag_cannot_inject_mentions_or_links():
    with pytest.raises(TweetError, match="hashtag"):
        finalize("Ali won 3-2 with 2 demos.", hashtag="#RL @someone")


def test_sanitizer_removes_duplicate_punctuation():
    assert sanitize_tweet("Ali won 3-2 with 2 demos?!?!!") == "Ali won 3-2 with 2 demos?"


class FakeProvider:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def generate(self, system, user):
        self.calls.append((system, user))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


@pytest.mark.parametrize("bad", [
    "Ali won 3-2 with 2 demos " + "x" * 300,
    "I cannot write this. Ali won 3-2 with 2 demos.",
    "Ali won with two demos and carried the team.",
    "Our team won 3-2 with two demos in style.",
])
def test_invalid_output_gets_one_shorter_retry(config, replay, bad):
    provider = FakeProvider(bad, "Ali won 3-2 with 2 demos. #other")
    tweet = generate_tweet(provider, extract_stats(replay, config.players), config)
    assert tweet == "Ali won 3-2 with 2 demos. #RocketLeague"
    assert len(provider.calls) == 2
    assert "shorter tweet" not in provider.calls[0][1]
    assert "shorter tweet" in provider.calls[1][1]


def test_two_invalid_answers_raise_without_template(config, replay):
    provider = FakeProvider("dummy-secret", "dummy-secret")
    with pytest.raises(AIError, match="validation after retry") as exc:
        generate_tweet(provider, extract_stats(replay, config.players), config)
    assert len(provider.calls) == 2
    assert "dummy-secret" not in str(exc.value)


def test_validation_failure_has_only_a_safe_category(config, replay):
    provider = FakeProvider("Ali played brilliantly and had two demos.", "Ali played brilliantly and had two demos.")
    with pytest.raises(AIValidationError) as exc:
        generate_tweet(provider, extract_stats(replay, config.players), config)
    assert exc.value.reason == "score"
    assert "Ali" not in str(exc.value)


def test_provider_failure_is_not_followed_by_generation_retry(config, replay):
    provider = FakeProvider(AIError("AI provider HTTP 401"))
    with pytest.raises(AIError, match="HTTP 401"):
        generate_tweet(provider, extract_stats(replay, config.players), config)
    assert len(provider.calls) == 1


def test_invalid_stats_fail_before_provider_call(config):
    provider = FakeProvider("unused")
    with pytest.raises(AIError, match="Invalid stats"):
        generate_tweet(provider, {"match": {}}, config)
    assert provider.calls == []


def test_mock_prompt_and_finalization_end_to_end(config, replay):
    text = generate_tweet(create_provider(config), extract_stats(replay, config.players), config)
    assert "Ali" in text and "Cam" in text and "3-2" in text and "2 demos" in text
    assert text.endswith("#RocketLeague") and weighted_length(text) <= 280


@pytest.mark.parametrize("text", [
    "Ali won 3-2 with 2 demos. https://example.com #RocketLeague",
    "Ali won 3-2 with 2 demos. @someone #RocketLeague",
    "Ali won 3-2 with 2 demos. #other #RocketLeague",
    "Ali won 3-2\nwith 2 demos. #RocketLeague",
    "Ali won 3-2 with 2 demos. #RocketLeague extra",
    "Ali won 3-2 with 2 demos. " + "x" * 280 + " #RocketLeague",
])
def test_cached_delivery_safety_rejects_unsafe_text(text):
    with pytest.raises(TweetError):
        validate_delivery_text(text, hashtag="#RocketLeague", max_weighted_len=280, allow_emoji=True)


def test_cached_delivery_safety_accepts_valid_text():
    validate_delivery_text("Ali won 3-2 with 2 demos. #RocketLeague", hashtag="#RocketLeague", max_weighted_len=280, allow_emoji=True)
