"""Manual delivery and local archives for validated tweets."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import pyperclip

from .store_utils import utc_stamp

logger = logging.getLogger("rl_analyzer")


class DeliveryError(RuntimeError):
    """A required local delivery file could not be written."""


@dataclass(frozen=True)
class DeliveryMetadata:
    """Allow-listed, non-secret information about a delivered tweet."""

    replay_id: str
    match_key: str
    match_date: str
    result: str | None
    score: dict[str, int] | None
    provider: str | None
    model: str | None
    status: str
    tweet_id: str | None = None

    def as_dict(self, now: datetime) -> dict[str, Any]:
        return {
            "replay_id": self.replay_id, "match_key": self.match_key,
            "match_url": f"https://ballchasing.com/replay/{quote(self.replay_id, safe='')}",
            "match_date": self.match_date, "result": self.result, "score": self.score,
            "provider": self.provider, "model": self.model, "status": self.status,
            "tweet_id": self.tweet_id, "delivered_at_utc": utc_stamp(now),
        }


def _write_atomic(path: Path, text: str) -> None:
    """Replace a file only after its UTF-8 content has been fully written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=path.parent,
                                         prefix=".rl-analyzer-", delete=False) as handle:
            name = handle.name
            handle.write(text)
        os.replace(name, path)
        name = None
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def deliver_tweet(text: str, metadata: DeliveryMetadata, output_dir: Path, *,
                  clipboard_enabled: bool = True, posted: bool = False, demo: bool = False,
                  now: datetime | None = None) -> None:
    """Write the tweet and metadata, archive it, print it, and optionally copy it."""
    now = now if now is not None else datetime.now(timezone.utc)
    stamp = utc_stamp(now)
    filename = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex + ".txt"
    output_dir = Path(output_dir)
    try:
        _write_atomic(output_dir / ("demo_tweet.txt" if demo else "tweet.txt"), text)
        _write_atomic(output_dir / "last_run.json", json.dumps(metadata.as_dict(now), ensure_ascii=False, indent=2) + "\n")
        _write_atomic(output_dir / "history" / filename, text)
        if posted:
            _write_atomic(output_dir / "posted" / filename, text)
    except (OSError, ValueError, TypeError):
        raise DeliveryError("Could not write tweet delivery files") from None
    try:
        print(f"\n--- Tweet ---\n{text}\n-------------")
    except UnicodeEncodeError:
        print(f"\n--- Tweet ---\n{text.encode('ascii', errors='backslashreplace').decode('ascii')}\n-------------")
    if clipboard_enabled:
        try:
            pyperclip.copy(text)
        except Exception:
            logger.warning("Clipboard unavailable; tweet was saved to file")
