"""Deterministic mock provider for tests and the offline demo only."""

import json
import math
from typing import Any

from .base import AIError, AIProvider


class MockProvider(AIProvider):
    """Build a deterministic synthetic response from supplied stats, never as fallback."""

    def generate(self, system: str, user: str) -> str:
        try:
            payload, _ = json.JSONDecoder().raw_decode(user.lstrip())
            match = payload["match"]
            players = payload["players"]
            score = match["score"]
            if not isinstance(players, list) or len(players) != 3 or any(not isinstance(p, dict) for p in players):
                raise ValueError
            standouts = [player for player in players if player.get("standout") is True]
            underperformers = [player for player in players if player.get("underperformer") is True]
            if len(standouts) != 1 or len(underperformers) != 1 or standouts[0] is underperformers[0]:
                raise ValueError
            standout, underperformer = standouts[0], underperformers[0]
            winner, loser = standout["alias"], underperformer["alias"]
            trio, opponent = score["trio"], score["opponents"]
            result = match["result"]
        except (KeyError, IndexError, TypeError, ValueError, StopIteration, AttributeError):
            raise AIError("Mock provider received invalid stats") from None
        if (not isinstance(winner, str) or not winner.strip() or not isinstance(loser, str) or not loser.strip()
                or isinstance(trio, bool) or not isinstance(trio, int) or trio < 0
                or isinstance(opponent, bool) or not isinstance(opponent, int) or opponent < 0
                or result != ("win" if trio > opponent else "loss" if trio < opponent else "draw")):
            raise AIError("Mock provider received invalid stats")

        stat = self._find_stat(players, standout)
        return f"A {result}, {trio}-{opponent}: {winner} led{stat}; {loser} brought the emotional support."

    @staticmethod
    def _find_stat(players: list[dict[str, Any]], standout: dict[str, Any]) -> str:
        for player in [standout, *[p for p in players if p is not standout]]:
            if not isinstance(player, dict) or not isinstance(player.get("alias"), str):
                continue
            for key, label in (("demos_inflicted", "demos"), ("demos_taken", "demos taken"),
                               ("boost_bpm", "boost BPM"), ("avg_boost", "average boost"),
                               ("time_zero_boost_seconds", "seconds at zero boost")):
                value = player.get(key)
                if (isinstance(value, (int, float)) and not isinstance(value, bool)
                        and (not isinstance(value, float) or math.isfinite(value))):
                    prefix = " with" if player is standout else f"; {player['alias']} had"
                    return f"{prefix} {value} {label}"
        return ""
