"""SQLite schema and version initialization, kept separate from store logic."""

import sqlite3

SCHEMA_VERSION = "1"

STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS replays (
        replay_id TEXT PRIMARY KEY,
        match_key TEXT NOT NULL,
        match_guid TEXT,
        rocket_league_id TEXT,
        match_date TEXT NOT NULL,
        result TEXT,
        trio_goals INTEGER,
        opponent_goals INTEGER,
        player_names TEXT,
        manual_delivered_at TEXT,
        status TEXT NOT NULL,
        tweet_text TEXT,
        tweet_id TEXT,
        reason TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        provider TEXT,
        model TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        posted_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_replays_match_key ON replays(match_key)",
    "CREATE INDEX IF NOT EXISTS idx_replays_status ON replays(status)",
    "CREATE INDEX IF NOT EXISTS idx_replays_match_date ON replays(match_date)",
    """CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        replay_id TEXT NOT NULL,
        tweet_id TEXT,
        text TEXT NOT NULL,
        posted_at TEXT NOT NULL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_posts_tweet_id_unique ON posts(tweet_id) WHERE tweet_id IS NOT NULL",
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)


def schema_version(connection: sqlite3.Connection) -> str | None:
    """Read the schema version without changing the database."""
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
    if not exists:
        return None
    row = connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return row[0] if row else None


def initialize(connection: sqlite3.Connection) -> None:
    """Create the known schema atomically and reject unknown versions."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        version = schema_version(connection)
        if version is not None and version != SCHEMA_VERSION:
            raise ValueError("Unsupported database schema version")
        for statement in STATEMENTS:
            connection.execute(statement)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(replays)")}
        for column, sql_type in (("result", "TEXT"), ("trio_goals", "INTEGER"), ("opponent_goals", "INTEGER"),
                                 ("player_names", "TEXT"), ("manual_delivered_at", "TEXT")):
            if column not in columns:
                connection.execute(f"ALTER TABLE replays ADD COLUMN {column} {sql_type}")
        connection.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
