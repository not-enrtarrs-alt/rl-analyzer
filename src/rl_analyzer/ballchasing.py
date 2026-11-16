"""Synchronous ballchasing JSON client with a shared request throttle."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import re
import time
from typing import Any, Callable, Sequence

import requests

from .config import Config


class BallchasingError(RuntimeError):
    """A safe-to-display ballchasing API failure."""


class BallchasingClient:
    """Fetch replay JSON; never download replay files or expose credentials."""

    def __init__(self, config: Config, *, session: requests.Session | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._base_url = config.ballchasing_base_url.rstrip("/")
        self._token = config.ballchasing_token
        self._interval = max(0.5, config.ballchasing_min_interval_seconds)
        self._timeout = config.request_timeout_seconds
        self._session = session or requests.Session()
        self._clock = clock
        self._sleep = sleep
        self._last_request: float | None = None

    def _throttle(self) -> None:
        if self._last_request is not None:
            delay = self._interval - (self._clock() - self._last_request)
            if delay > 0:
                self._sleep(delay)
        self._last_request = self._clock()

    @staticmethod
    def _retry_after(value: str | None) -> float:
        if not value:
            return 0.0
        try:
            seconds = float(value)
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                seconds = (date - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                return 0.0
        return max(0.0, seconds) if math.isfinite(seconds) else 0.0

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(4):
            self._throttle()
            try:
                response = self._session.get(
                    f"{self._base_url}{path}", params=params,
                    headers={"Authorization": self._token}, timeout=self._timeout,
                )
            except requests.RequestException:
                raise BallchasingError("Ballchasing request failed; check connectivity") from None
            status = response.status_code
            if status in (401, 403):
                raise BallchasingError(f"Ballchasing HTTP {status}; check BALLCHASING_TOKEN")
            if status == 429 or 500 <= status <= 599:
                if attempt == 3:
                    raise BallchasingError(f"Ballchasing HTTP {status}; retries exhausted")
                delay = max(2 ** attempt, self._retry_after(response.headers.get("Retry-After")))
                self._sleep(delay)
                continue
            if status != 200:
                raise BallchasingError(f"Ballchasing HTTP {status}")
            try:
                body = response.json()
            except ValueError:
                raise BallchasingError("Ballchasing returned invalid JSON") from None
            if not isinstance(body, dict):
                raise BallchasingError("Ballchasing returned an invalid JSON object")
            return body
        raise AssertionError("unreachable")

    def list_replays(self, player_id: str, cutoff: datetime) -> list[dict[str, Any]]:
        """List up to 200 replays for one player since an aware UTC cutoff."""
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("cutoff must have a timezone")
        stamp = cutoff.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        body = self._get("/replays", {
            "player-id": player_id, "replay-date-after": stamp, "count": 200,
            "sort-by": "replay-date", "sort-dir": "desc",
        })
        items = body.get("list")
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise BallchasingError("Ballchasing returned an invalid replay list")
        return items

    def list_common_replays(self, player_ids: Sequence[str], cutoff: datetime) -> list[dict[str, Any]]:
        """Intersect replay IDs from three independently filtered player lists."""
        if len(player_ids) != 3 or len(set(player_ids)) != 3:
            raise ValueError("Exactly three unique player IDs are required")
        lists = [self.list_replays(player_id, cutoff) for player_id in player_ids]
        id_sets = [{item.get("id") for item in items if isinstance(item.get("id"), str) and item["id"]} for items in lists]
        common = set.intersection(*id_sets)
        seen: set[str] = set()
        result = []
        for item in lists[0]:
            replay_id = item.get("id")
            if isinstance(replay_id, str) and replay_id in common and replay_id not in seen:
                seen.add(replay_id)
                result.append(item)
        return result

    def get_replay(self, replay_id: str) -> dict[str, Any]:
        """Fetch a single replay's JSON details."""
        if not re.fullmatch(r"[A-Za-z0-9_-]+", replay_id):
            raise BallchasingError("Invalid replay ID")
        return self._get(f"/replays/{replay_id}")
