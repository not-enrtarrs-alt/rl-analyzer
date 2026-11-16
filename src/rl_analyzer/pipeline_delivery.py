"""Cached tweet validation and guarded delivery for the daily pipeline."""

from datetime import datetime, timedelta
import json
import logging
from typing import Any, Callable

from .config import Config
from .delivery import DeliveryError, DeliveryMetadata, deliver_tweet
from .stats import InvalidReplay, parse_replay_date
from .store import Store, StoreError
from .tweet import TweetError, finalize_tweet
from .x_client import XClient, XError

logger = logging.getLogger("rl_analyzer")


def validate_cached(row: dict[str, Any], config: Config) -> None:
    """Revalidate a persisted tweet without changing its exact text."""
    try:
        score = (row["trio_goals"], row["opponent_goals"])
        expected_result = "win" if score[0] > score[1] else "loss" if score[0] < score[1] else "draw"
        if row["result"] != expected_result:
            raise ValueError
        names = json.loads(row["player_names"]) if row.get("player_names") else [player.alias for player in config.players]
        if not isinstance(names, list):
            raise ValueError
        result = finalize_tweet(row["tweet_text"], score=score, names=names,
                                hashtag=config.tweet_hashtag, max_weighted_len=config.tweet_max_weighted_len,
                                allow_emoji=config.tweet_allow_emoji)
        if result != row["tweet_text"]:
            raise ValueError
    except (KeyError, TypeError, ValueError, TweetError):
        raise StoreError("Cached tweet failed validation; inspect before delivery") from None


def metadata_from_row(row: dict[str, Any], status: str, tweet_id: str | None = None) -> DeliveryMetadata:
    """Build allow-listed output metadata from a replay record."""
    return DeliveryMetadata(row["replay_id"], row["match_key"], row["match_date"], row["result"],
                            {"trio": row["trio_goals"], "opponents": row["opponent_goals"]},
                            row["provider"], row["model"], status, tweet_id)


def deliver_cached(row: dict[str, Any], config: Config, store: Store, now: datetime, *,
                   x_client: XClient | None = None, clock: Callable[[], datetime] | None = None) -> int:
    """Deliver a generated row without another AI call; return a CLI exit code."""
    try:
        validate_cached(row, config)
    except StoreError:
        logger.error("Cached tweet failed validation; inspect before delivery")
        return 5 if config.post_to_x else 6
    replay_id, text = row["replay_id"], row["tweet_text"]
    clock = clock if clock is not None else lambda: now
    if config.post_to_x:
        if row["provider"] == "mock":
            logger.error("Mock-generated tweets cannot be posted live")
            return 5
        store.start_posting(replay_id, now=now)
        client = x_client if x_client is not None else XClient(config)
        try:
            tweet_id = client.post(text)
        except XError as exc:
            store.mark_post_failed(replay_id, outcome_known=exc.outcome_known, now=clock())
            logger.error("%s; %s", exc.safe_diagnostic(), "cached text retained" if exc.outcome_known else "outcome unknown; inspect manually")
            return 5
        except Exception:
            store.mark_post_failed(replay_id, outcome_known=False, now=clock())
            logger.error("X posting outcome is unknown; inspect manually")
            return 5
        posted = store.mark_posted(replay_id, tweet_id, now=clock())
        try:
            deliver_tweet(text, metadata_from_row(posted, "posted", tweet_id), config.manual_output_dir,
                          clipboard_enabled=config.clipboard_enabled, posted=True, now=clock())
        except DeliveryError:
            logger.error("Post succeeded but local archive failed; do not repost")
            return 6
        return 0
    try:
        deliver_tweet(text, metadata_from_row(row, "manual"), config.manual_output_dir,
                      clipboard_enabled=config.clipboard_enabled, now=now)
    except DeliveryError:
        logger.error("Manual delivery failed; cached text retained")
        return 6
    store.mark_manual_delivered(replay_id, now=clock())
    return 0


def deliver_pending(config: Config, store: Store, now: datetime, *, x_client: XClient | None = None,
                    clock: Callable[[], datetime] | None = None) -> int | None:
    """Deliver the newest eligible cached tweet, or continue if none exists."""
    row = store.latest_pending() if config.post_to_x else store.latest_undelivered()
    if not row:
        return None
    try:
        date = parse_replay_date(row["match_date"])
    except (KeyError, InvalidReplay):
        raise StoreError("Cached replay date is invalid") from None
    if date > now:
        raise StoreError("Cached replay date is in the future")
    if date < now - timedelta(hours=config.max_replay_age_hours):
        store.skip_expired(row["replay_id"], now=now)
        logger.info("Cached replay expired before delivery")
        return None
    return deliver_cached(row, config, store, now, x_client=x_client, clock=clock)
