"""Command-line entry points: db-setup, collect, sync, analyze, report."""

import argparse
import sys
from collections.abc import Callable, Sequence

from scout_ai import __version__


def db_setup() -> int:
    """Create the database if missing, apply migrations and seed competitors (guide Step 2)."""
    from scout_ai.config import get_settings
    from scout_ai.db.setup import setup_database

    setup_database(get_settings().database_url)
    return 0


def collect() -> int:
    """Fetch competitor sources and store new snapshots (guide Step 3)."""
    print("collect: not implemented yet")
    return 1


def sync() -> int:
    """Pull internal data from HubSpot and ClickUp (guide Step 5)."""
    print("sync: not implemented yet")
    return 1


def analyze() -> int:
    """Extract signals and generate recommendations with the LLM (guide Steps 4 and 7)."""
    print("analyze: not implemented yet")
    return 1


def report() -> int:
    """Build and deliver the weekly summary (guide Step 6)."""
    print("report: not implemented yet")
    return 1


COMMANDS: dict[str, Callable[[], int]] = {
    "db-setup": db_setup,
    "collect": collect,
    "sync": sync,
    "analyze": analyze,
    "report": report,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scout", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, func in COMMANDS.items():
        subparsers.add_parser(name, help=func.__doc__)

    args = parser.parse_args(argv)
    return COMMANDS[args.command]()


if __name__ == "__main__":
    sys.exit(main())
