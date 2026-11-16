"""Select the newest eligible replay without consuming older backlog games."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Protocol

from .ballchasing import BallchasingClient
from .config import Config
from .stats import InvalidReplay, extract_stats, parse_replay_date

logger = logging.getLogger("rl_analyzer")


class SelectionStore(Protocol):
    """Dedupe operations supplied by persistent storage in M2."""

    def replay_is_consumed(self, replay_id: str) -> bool: ...
    def match_is_consumed(self, match_key: str, *, exclude_replay_id: str,
                          match_guid: str | None = None, rocket_league_id: str | None = None) -> bool: ...
    def record_duplicate(self, replay: dict[str, Any], match_key: str) -> None: ...


@dataclass(frozen=True)
class Candidate:
    """Eligible replay and its already-validated extraction."""

    replay: dict[str, Any]
    match_key: str
    match_date: datetime
    stats: dict[str, Any]


def match_key(replay: dict[str, Any]) -> str:
    """Use the canonical match identifier, falling back to the replay ID."""
    for name in ("match_guid", "rocket_league_id", "id"):
        value = replay.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise InvalidReplay("Replay has no match or replay ID")


def select_candidate(client: BallchasingClient, config: Config, now: datetime, *,
                     store: SelectionStore | None = None,
                     record_duplicates: bool = False) -> Candidate | None:
    """Inspect newest eligible replay; do not mark unselected backlog consumed.

    A real run must pass a store; previews may disable duplicate recording while
    still consulting that store. The detail response is reused by the caller.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must have a timezone")
    now = now.astimezone(timezone.utc)
    cutoff = now - timedelta(hours=config.max_replay_age_hours)
    summaries = client.list_common_replays([player.id for player in config.players], cutoff)
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for summary in summaries:
        replay_id = summary.get("id")
        if not isinstance(replay_id, str) or not replay_id.strip():
            continue
        try:
            date = parse_replay_date(summary.get("date"))
        except InvalidReplay:
            continue
        if not cutoff <= date <= now or (store and store.replay_is_consumed(replay_id)):
            continue
        # A summary may omit match IDs; only prefilter on a real match identifier.
        if store and any(isinstance(summary.get(k), str) and summary[k].strip()
                         for k in ("match_guid", "rocket_league_id")):
            key = match_key(summary)
            if store.match_is_consumed(key, exclude_replay_id=replay_id,
                                       match_guid=summary.get("match_guid"), rocket_league_id=summary.get("rocket_league_id")):
                if record_duplicates:
                    store.record_duplicate(summary, key)
                continue
        candidates.append((date, summary))
    candidates.sort(key=lambda item: item[0], reverse=True)

    for summary_date, summary in candidates[:config.max_candidates_to_inspect]:
        replay_id = summary["id"]
        detail = client.get_replay(replay_id)
        if detail.get("id") != replay_id:
            logger.warning("Replay detail ID does not match the requested replay")
            continue
        try:
            date = parse_replay_date(detail.get("date"))
            key = match_key(detail)
        except InvalidReplay:
            continue
        if not cutoff <= date <= now:
            continue
        if date != summary_date:
            logger.warning("Replay detail date differs from its list date; ignoring inconsistent replay")
            continue
        if store and store.match_is_consumed(key, exclude_replay_id=replay_id,
                                             match_guid=detail.get("match_guid"), rocket_league_id=detail.get("rocket_league_id")):
            if record_duplicates:
                store.record_duplicate(detail, key)
            continue
        if (detail.get("status") != "ok" or detail.get("team_size") != 3
                or detail.get("playlist_id") not in config.allowed_playlists):
            continue
        try:
            stats = extract_stats(detail, config.players)
        except InvalidReplay:
            continue
        return Candidate(detail, key, date, stats)
    return None
