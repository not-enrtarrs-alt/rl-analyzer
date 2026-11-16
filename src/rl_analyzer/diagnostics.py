"""Non-posting configuration, storage, clipboard and optional live checks."""

from pathlib import Path
import sqlite3
import tempfile

import pyperclip
import requests

from .ai.base import _protect_http_logs
from .ai import provider_model
from .config import Config
from .store import Store, StoreError


def _directory(label: str, path: Path) -> bool:
    """Probe an existing directory or its nearest existing parent without creating it."""
    if path.exists() and not path.is_dir():
        print(f"ERROR: {label} path is not a directory")
        return False
    parent = path
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    try:
        with tempfile.TemporaryFile(dir=parent) as handle:
            handle.write(b"ok")
        print(f"{label}: writable" + (" (will be created on use)" if parent != path else ""))
        return True
    except OSError:
        print(f"ERROR: {label} directory is not writable")
        return False


def _database(config: Config) -> bool:
    if not config.database_path.exists():
        print("Database: not created yet")
        return True
    try:
        with Store(config.database_path, readonly=True) as store:
            posting = store.posting_rows()
            analyses = store.inflight_analyses()
        print("Database: readable, schema supported")
        if posting:
            print(f"WARNING: {len(posting)} in-flight or unknown post(s); inspect manually before posting")
        if analyses:
            print(f"WARNING: {len(analyses)} in-flight analysis reservation(s); inspect manually")
        return True
    except (StoreError, sqlite3.Error, OSError):
        print("ERROR: Database cannot be read or has an unsupported schema")
        return False


def _clipboard(config: Config) -> None:
    if not config.clipboard_enabled:
        print("Clipboard: disabled")
        return
    try:
        pyperclip.paste()  # Discard contents; do not modify or print the clipboard.
        print("Clipboard: readable")
    except Exception:
        print("WARNING: Clipboard unavailable; file delivery still works")


def _live_checks(config: Config) -> None:
    if not config.ballchasing_token:
        print("WARNING: Ballchasing live check skipped; token missing")
    else:
        try:
            with _protect_http_logs([config.ballchasing_token]):
                response = requests.get(f"{config.ballchasing_base_url.rstrip('/')}/",
                    headers={"Authorization": config.ballchasing_token}, timeout=config.request_timeout_seconds,
                    allow_redirects=False)
            if response.status_code == 200:
                print("Ballchasing: authenticated endpoint reachable")
            elif response.status_code in (401, 403):
                print("WARNING: Ballchasing authentication failed; check BALLCHASING_TOKEN")
            else:
                print(f"WARNING: Ballchasing returned HTTP {response.status_code}")
        except requests.RequestException:
            print("WARNING: Ballchasing endpoint unreachable")
    try:
        response = requests.get(f"{config.ollama_base_url.rstrip('/')}/api/tags",
                                timeout=config.request_timeout_seconds, allow_redirects=False)
        if response.status_code != 200:
            print(f"WARNING: Ollama returned HTTP {response.status_code}")
            return
        body = response.json()
        models = body.get("models") if isinstance(body, dict) else None
        if not isinstance(models, list):
            raise ValueError
        names = {item.get("name") for item in models if isinstance(item, dict) and isinstance(item.get("name"), str)}
        expected = config.ollama_model if ":" in config.ollama_model else config.ollama_model + ":latest"
        print("Ollama: configured model available" if config.ollama_model in names or expected in names
              else "WARNING: Ollama configured model not installed")
    except (requests.RequestException, ValueError, TypeError):
        print("WARNING: Ollama unavailable or returned invalid model list")


def report(config: Config, *, live: bool = False) -> int:
    """Report diagnostics; never send a post or reveal credential values."""
    print(f"Configured players: {len(config.players)} of 3")
    print(f"AI provider: {config.ai_provider}")
    if config.ai_provider != "mock" and not provider_model(config):
        print("WARNING: Selected AI model is not configured")
    print(f"X posting: {'enabled' if config.post_to_x else 'disabled'}")
    x_ready = (all((config.x_api_key, config.x_api_secret, config.x_access_token, config.x_access_secret))
               if config.x_auth_mode == "oauth1" else bool(config.x_oauth2_user_token))
    print(f"X credentials: {'present' if x_ready else 'missing' + (' (optional until enabled)' if not config.post_to_x else '')}")
    for warning in config.warnings:
        print(f"WARNING: {warning}")
    checks = [_directory("Output", config.manual_output_dir), _directory("Logs", config.log_dir),
              _directory("Database parent", config.database_path.parent), _database(config)]
    _clipboard(config)
    if live:
        _live_checks(config)
    else:
        print("Network checks skipped; use doctor --live to check ballchasing and Ollama.")
    print("X posting is never tested by doctor.")
    return 0 if all(checks) else 6
