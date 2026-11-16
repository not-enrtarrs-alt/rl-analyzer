"""Read-only human-readable replay history."""

from pathlib import Path
import sqlite3

from .store import Store, StoreError


def print_history(database_path: Path, limit: int = 10) -> int:
    """Print recent result, score, status, ID and tweet preview without DB writes."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        print("ERROR: history limit must be positive")
        return 2
    if not database_path.exists():
        print("No history yet.")
        return 0
    try:
        with Store(database_path, readonly=True) as store:
            rows = store.recent_replays(limit)
    except (StoreError, sqlite3.Error, OSError):
        print("ERROR: Database cannot be read or has an unsupported schema")
        return 6
    if not rows:
        print("No history yet.")
        return 0
    for row in rows:
        goals, opponents = row.get("trio_goals"), row.get("opponent_goals")
        score = f"{goals}-{opponents}" if goals is not None and opponents is not None else "?"
        text = " ".join((row.get("tweet_text") or "").split())
        preview = text if len(text) <= 80 else text[:77] + "..."
        print(f"{row['match_date']} | {row.get('result') or '?'} {score} | {row['status']} | {row.get('tweet_id') or '-'} | {preview}")
    return 0
