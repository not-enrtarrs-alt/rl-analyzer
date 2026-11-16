"""Daily selection, AI generation and safe delivery orchestration."""

from contextlib import nullcontext
from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from typing import Callable, Any

from .ai import create_provider, provider_model
from .ai.base import AIError, AIProvider, AIValidationError
from .ballchasing import BallchasingClient, BallchasingError
from .config import Config, ConfigError, ROOT, load_config
from .delivery import DeliveryError, DeliveryMetadata, deliver_tweet
from .logging_setup import setup_logging
from .pipeline_delivery import deliver_pending
from .run_lock import RunLock
from .select import select_candidate
from .store import Store, StoreError
from .store_utils import utc_stamp
from .tweet import generate_tweet
from .x_client import XClient, XError

logger = logging.getLogger("rl_analyzer")


class _SingleReplay:
    """Reuse a single fetched detail while applying normal eligibility checks."""

    def __init__(self, client: BallchasingClient, replay_id: str) -> None:
        self.detail = client.get_replay(replay_id)
        if self.detail.get("id") != replay_id:
            raise BallchasingError("Replay detail ID does not match request")

    def list_common_replays(self, player_ids: list[str], cutoff: datetime) -> list[dict[str, Any]]:
        return [self.detail]

    def get_replay(self, replay_id: str) -> dict[str, Any]:
        return self.detail


def _run(config: Config, *, dry_run: bool, force: bool, replay_id: str | None,
         client: BallchasingClient | None, provider: AIProvider | None,
         x_client: XClient | None, clock: Callable[[], datetime]) -> int:
    database = config.database_path
    if dry_run:
        context = Store(database, readonly=True) if database.exists() else nullcontext(None)
    else:
        context = Store(database)
    with context as store:
        now = clock()
        if not dry_run and store is not None:
            if not force and store.in_cooldown(now, config.cooldown_hours):
                logger.info("Cooldown active; no action taken")
                return 0
            if config.post_to_x and store.posting_rows():
                logger.warning("An in-flight or unknown post requires manual inspection")
                return 5
            pending = deliver_pending(config, store, now, x_client=x_client, clock=clock)
            if pending is not None:
                return pending

        api = client if client is not None else BallchasingClient(config)
        selection_api = _SingleReplay(api, replay_id) if replay_id else api
        candidate = select_candidate(selection_api, config, now, store=store,
                                     record_duplicates=not dry_run)
        if candidate is None:
            logger.info("No new eligible replay")
            return 0
        if not dry_run and config.post_to_x and config.ai_provider == "mock":
            logger.error("Mock AI cannot be used for live posting")
            return 2
        ai = provider if provider is not None else create_provider(config)
        model = provider_model(config)
        if dry_run:
            text = generate_tweet(ai, candidate.stats, config)
            match = candidate.stats["match"]
            metadata = DeliveryMetadata(candidate.replay["id"], candidate.match_key,
                utc_stamp(candidate.match_date), match["result"], match["score"],
                config.ai_provider, model, "dry_run")
            deliver_tweet(text, metadata, config.manual_output_dir,
                          clipboard_enabled=config.clipboard_enabled, now=clock())
            return 0

        assert store is not None
        names = [name for player in candidate.stats["players"]
                 for name in (player.get("alias"), player.get("in_game_name"))
                 if isinstance(name, str) and name.strip()]
        reservation = store.reserve_analysis(candidate.replay, match=candidate.stats["match"], names=names,
                                             provider=config.ai_provider, model=model, now=clock())
        owner_id = reservation["replay_id"]
        try:
            text = generate_tweet(ai, candidate.stats, config)
        except AIError:
            store.mark_analysis_failed(owner_id, now=clock())
            raise
        store.save_generated(owner_id, text, now=clock())
        result = deliver_pending(config, store, clock(), x_client=x_client, clock=clock)
        return result if result is not None else 0


def run_daily(*, config: Config | None = None, dry_run: bool = False, force: bool = False,
              replay_id: str | None = None, verbose: bool = False,
              client: BallchasingClient | None = None, provider: AIProvider | None = None,
              x_client: XClient | None = None, lock_path: Path | None = None,
              clock: Callable[[], datetime] | None = None) -> int:
    """Run once, mapping failures to documented exit codes without exposing secrets."""
    clock = clock if clock is not None else lambda: datetime.now(timezone.utc)

    def execute() -> int:
        settings = config if config is not None else load_config()
        setup_logging(settings.log_dir, settings.log_level, verbose=verbose)
        return _run(settings, dry_run=dry_run, force=force, replay_id=replay_id,
                    client=client, provider=provider, x_client=x_client, clock=clock)

    try:
        if dry_run:
            return execute()
        with RunLock(lock_path or ROOT / "data" / "run.lock") as acquired:
            if not acquired:
                logger.info("Another run holds the lock; exiting")
                return 0
            return execute()
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        return 2
    except BallchasingError as exc:
        logger.error("Ballchasing error: %s", exc)
        return 3
    except AIValidationError as exc:
        logger.error("AI output failed validation after retry: %s", exc.reason)
        return 4
    except AIError:
        logger.error("AI generation failed; no tweet delivered")
        return 4
    except XError as exc:
        logger.error("X error: %s", exc)
        return 5
    except (StoreError, DeliveryError, sqlite3.Error, OSError, ValueError):
        logger.error("Storage, delivery or lock error; inspect local state")
        return 6
    except Exception:
        logger.error("Unexpected failure; inspect local state")
        return 6
