"""Extract only known statistics for the configured trio from replay JSON."""

from datetime import datetime, timezone
import logging
import math
from typing import Any, Sequence

from .config import ConfigError, normalize_player_id
from .models import Player


class InvalidReplay(ValueError):
    """Replay is unsuitable for a reliable recap."""


def parse_replay_date(value: Any) -> datetime:
    """Parse an ISO date as UTC, warning when a timezone was omitted."""
    if not isinstance(value, str):
        raise InvalidReplay("Replay date is missing or invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidReplay("Replay date is missing or invalid") from None
    if result.tzinfo is None:
        logging.getLogger("rl_analyzer").warning("Replay date is naive; assuming UTC")
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return round(value, 1) if isinstance(value, float) else value


def _player_id(player: dict[str, Any]) -> str | None:
    identity = _mapping(player.get("id"))
    platform, ident = identity.get("platform"), identity.get("id")
    if not isinstance(platform, str) or not isinstance(ident, str):
        return None
    try:
        return normalize_player_id(f"{platform}:{ident}")
    except ConfigError:
        return None


def find_trio_team(replay: dict[str, Any], players: Sequence[Player]) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    """Find the single team containing all three distinct configured IDs."""
    wanted = {player.id for player in players}
    if len(players) != 3 or len(wanted) != 3:
        raise InvalidReplay("Exactly three unique players are required")
    teams = [_mapping(replay.get("blue")), _mapping(replay.get("orange"))]
    indexed: list[dict[str, dict[str, Any]]] = []
    for team in teams:
        roster = team.get("players")
        if not isinstance(roster, list):
            raise InvalidReplay("Team player list is missing")
        found: dict[str, dict[str, Any]] = {}
        for raw in roster:
            if not isinstance(raw, dict):
                continue
            identity = _player_id(raw)
            if identity in wanted:
                if identity in found:
                    raise InvalidReplay("Duplicate player ID in team")
                found[identity] = raw
        indexed.append(found)
    matches = [index for index, found in enumerate(indexed) if wanted.issubset(found)]
    if len(matches) != 1 or set(indexed[0]) & set(indexed[1]):
        raise InvalidReplay("Trio is not on one team")
    index = matches[0]
    return teams[index], teams[1 - index], indexed[index]


def _goal_count(team: dict[str, Any]) -> int:
    value = team.get("goals")
    if value is None:
        value = _mapping(_mapping(team.get("stats")).get("core")).get("goals")
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or (isinstance(value, float) and not math.isfinite(value))
            or value < 0 or int(value) != value):
        raise InvalidReplay("Team goals are missing or invalid")
    return int(value)


def _sections(owner: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    stats = _mapping(owner.get("stats"))
    return _mapping(stats.get("core")), _mapping(stats.get("boost")), _mapping(stats.get("demo"))


def extract_stats(replay: dict[str, Any], players: Sequence[Player]) -> dict[str, Any]:
    """Build a compact stats payload, using null for missing optional fields."""
    trio, opponent, roster = find_trio_team(replay, players)
    goals, against = _goal_count(trio), _goal_count(opponent)
    extracted: list[dict[str, Any]] = []
    for configured in players:
        player = roster[configured.id]
        core, boost, demo = _sections(player)
        score = _number(core.get("score"))
        if score is None or score < 0:
            raise InvalidReplay("Player core score is missing or invalid")
        mvp = player.get("mvp") if player.get("mvp") is not None else core.get("mvp")
        if not isinstance(mvp, bool):
            mvp = bool(mvp) if isinstance(mvp, int) and mvp in (0, 1) else None
        extracted.append({
            "alias": configured.alias or player.get("name"), "in_game_name": player.get("name"),
            "goals": _number(core.get("goals")), "assists": _number(core.get("assists")),
            "saves": _number(core.get("saves")), "shots": _number(core.get("shots")), "score": score,
            "shooting_pct": _number(core.get("shooting_percentage")),
            "demos_inflicted": _number(demo.get("inflicted")), "demos_taken": _number(demo.get("taken")),
            "boost_bpm": _number(boost.get("bpm")), "avg_boost": _number(boost.get("avg_amount")),
            "time_zero_boost_seconds": _number(boost.get("time_zero_boost")), "mvp": mvp,
        })
    def impact(player: dict[str, Any]) -> tuple[float, float, float]:
        return tuple(player[key] if player[key] is not None else float("-inf") for key in ("score", "goals", "saves"))

    extracted.sort(key=impact, reverse=True)
    extracted[0]["standout"] = True
    extracted[-1]["underperformer"] = True
    core, boost, demo = _sections(trio)
    totals = {key: _number(core.get(key)) for key in ("goals", "assists", "saves", "shots", "score")}
    totals.update({
        "demos_inflicted": _number(demo.get("inflicted")), "demos_taken": _number(demo.get("taken")),
        "boost_bpm": _number(boost.get("bpm")), "avg_boost": _number(boost.get("avg_amount")),
        "time_zero_boost_seconds": _number(boost.get("time_zero_boost")),
    })
    date = parse_replay_date(replay.get("date")).isoformat().replace("+00:00", "Z")
    return {
        "match": {
            "date_utc": date, "playlist": replay.get("playlist_name") or replay.get("playlist_id"),
            "map": replay.get("map_name"), "duration_seconds": _number(replay.get("duration")),
            "overtime": replay.get("overtime") if isinstance(replay.get("overtime"), bool) else None,
            "result": "win" if goals > against else "loss" if goals < against else "draw",
            "score": {"trio": goals, "opponents": against},
        },
        "players": extracted,
        "team_totals": totals,
    }
