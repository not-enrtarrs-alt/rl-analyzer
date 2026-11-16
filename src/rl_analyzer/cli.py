"""Command-line entry point and initial offline diagnostics."""

import argparse
import sys
from typing import Sequence

from .config import ConfigError, load_config
from .demo import run_demo
from .diagnostics import report as diagnostics_report
from .history import print_history
from .pipeline import run_daily


def build_parser() -> argparse.ArgumentParser:
    """Create the command interface."""
    parser = argparse.ArgumentParser(prog="rl_analyzer")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run the daily pipeline")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--force", action="store_true")
    run.add_argument("--verbose", action="store_true")
    preview = commands.add_parser("preview", help="Inspect without posting or database writes")
    preview.add_argument("--replay-id")
    preview.add_argument("--verbose", action="store_true")
    commands.add_parser("demo", help="Run the offline fixture demo")
    doctor = commands.add_parser("doctor", help="Check configuration")
    modes = doctor.add_mutually_exclusive_group()
    modes.add_argument("--offline", action="store_true")
    modes.add_argument("--live", action="store_true")
    history = commands.add_parser("history", help="Show previous runs")
    history.add_argument("--limit", type=int, default=10)
    return parser


def doctor(*, live: bool = False) -> int:
    """Report configuration and optionally check services without posting."""
    print(f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    if sys.version_info < (3, 11):
        print("ERROR: Python 3.11 or newer is required")
        return 2
    try:
        config = load_config(allow_incomplete=True)
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 2
    return diagnostics_report(config, live=live)


def main(argv: Sequence[str] | None = None) -> int:
    """Execute a CLI command and return its process exit code."""
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return doctor(live=args.live)
    if args.command == "run":
        return run_daily(dry_run=args.dry_run, force=args.force, verbose=args.verbose)
    if args.command == "preview":
        return run_daily(dry_run=True, replay_id=args.replay_id, verbose=args.verbose)
    if args.command == "demo":
        return run_demo()
    if args.command == "history":
        if args.limit <= 0:
            print("ERROR: history limit must be positive")
            return 2
        try:
            config = load_config(allow_incomplete=True)
        except ConfigError as exc:
            print(f"ERROR: {exc}")
            return 2
        return print_history(config.database_path, args.limit)
    print(f"{args.command}: not implemented yet; see docs/PLAN.md", file=sys.stderr)
    return 6
