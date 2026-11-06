"""Command-line entry points: db-setup, collect, fetch, load, analyze, recommend, report."""

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
    from collections import Counter

    import httpx
    from sqlalchemy.orm import Session

    from scout_ai.collectors import build_collectors
    from scout_ai.collectors.http import PoliteClient
    from scout_ai.collectors.run import Status, collect_sources
    from scout_ai.config import get_settings
    from scout_ai.db.session import get_engine

    settings = get_settings()
    with (
        httpx.Client(follow_redirects=True, timeout=30.0) as client,
        Session(get_engine()) as session,
    ):
        http = PoliteClient(
            client,
            user_agent=settings.collector_user_agent,
            delay=settings.collector_delay_seconds,
        )
        results = collect_sources(session, build_collectors(http))

    for result in results:
        detail = f" ({result.detail})" if result.detail else ""
        print(
            f"  {result.status:<11} {result.competitor} {result.source_type}: {result.url}{detail}"
        )
    totals = Counter(result.status for result in results)
    print(_counts({str(status): totals[status] for status in Status if totals[status]}))
    # Blocked and unsupported sources are expected; only real failures need attention.
    return 1 if totals[Status.FAILED] else 0


def fetch() -> int:
    """Read HubSpot and the Marketing CSVs, write the synthetic demo dataset (guide Step 5)."""
    from pathlib import Path

    from scout_ai.config import get_settings
    from scout_ai.demo.synthesize import compare, synthesize, write_dataset
    from scout_ai.integrations import marketing_csv
    from scout_ai.integrations.hubspot import fetch_deals

    settings = get_settings()
    if settings.hubspot_token is None:
        print("fetch: set HUBSPOT_TOKEN in .env", file=sys.stderr)
        return 1
    raw_dir = Path(settings.raw_data_dir)
    try:
        spend_csv = marketing_csv.find_export(raw_dir, marketing_csv.SPEND_PATTERN)
        mql_csv = marketing_csv.find_export(raw_dir, marketing_csv.MQL_PATTERN)
    except marketing_csv.MarketingCSVError as error:
        print(f"fetch: {error}", file=sys.stderr)
        return 1
    spend = marketing_csv.read_spend(spend_csv)
    mqls = marketing_csv.read_mqls(mql_csv)
    if not spend:
        print(f"fetch: no spend rows in {spend_csv.name}", file=sys.stderr)
        return 1
    # Same period as the Marketing exports, so funnel and spend cover the same months.
    since = min(row.period for row in spend)
    deals = fetch_deals(settings.hubspot_token.get_secret_value(), since=since)

    tables = synthesize(deals, spend, mqls, seed=settings.demo_seed)
    manifest = write_dataset(tables, Path(settings.demo_data_dir), seed=settings.demo_seed)
    print(f"Read {len(deals)} deals, {len(mqls)} MQLs and {len(spend)} spend rows since {since}.")
    print(f"Wrote {settings.demo_data_dir}: " + _counts(manifest.row_counts))

    checks = compare(deals, spend, mqls, tables)
    print("\nSynthetic vs real (percentage points):")
    for check in checks:
        mark = "ok  " if check.ok else "FAIL"
        rule = f"tolerance {check.tolerance_pp:.1f}" + (
            ", must differ" if check.must_differ else ""
        )
        print(f"  {mark} {check.metric:<45} diff {check.diff_pp:+.1f}  ({rule})")
    return 0 if all(check.ok for check in checks) else 1


def load() -> int:
    """Load the synthetic demo dataset from data/demo/ into the database (guide Step 5)."""
    from pathlib import Path

    from sqlalchemy.orm import Session

    from scout_ai.config import get_settings
    from scout_ai.db.session import get_engine
    from scout_ai.demo.load import DemoDatasetError, load_dataset

    try:
        with Session(get_engine()) as session:
            counts = load_dataset(Path(get_settings().demo_data_dir), session)
    except DemoDatasetError as error:
        print(f"load: {error}", file=sys.stderr)
        return 1
    print("Loaded " + _counts(counts))
    return 0


def _counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{table} {rows}" for table, rows in counts.items())


def analyze() -> int:
    """Extract signals from new snapshots with the LLM (guide Step 4)."""
    import asyncio
    from collections import Counter

    from sqlalchemy.orm import Session

    from scout_ai.analysis.signals import Status, analyze_snapshots
    from scout_ai.db.session import get_engine

    with Session(get_engine()) as session:
        results = asyncio.run(analyze_snapshots(session))

    for result in results:
        if result.status is Status.BASELINE:
            continue  # first snapshot of a source: nothing to report
        detail = f" ({result.detail})" if result.detail else ""
        count = f" {result.signals}" if result.signals else ""
        print(f"  {result.status:<9}{count} {result.competitor}: {result.url}{detail}")
    totals = Counter(result.status for result in results)
    signals = sum(result.signals for result in results)
    summary = {str(status): totals[status] for status in Status if totals[status]}
    print((_counts(summary) or "nothing to analyze") + f"; {signals} new signals")
    return 1 if totals[Status.FAILED] else 0


def recommend() -> int:
    """Propose prioritized Marketing actions from signals and internal data (guide Step 7)."""
    import asyncio

    from pydantic import ValidationError
    from sqlalchemy.orm import Session

    from scout_ai import llm
    from scout_ai.analysis.recommendations import generate_recommendations
    from scout_ai.db.session import get_engine

    with Session(get_engine()) as session:
        try:
            result = asyncio.run(generate_recommendations(session))
        except (llm.LLMError, ValidationError) as error:
            print(f"recommend: {str(error).splitlines()[0]}", file=sys.stderr)
            return 1
        if result.skipped:
            print(f"Nothing to recommend: {result.skipped}")
            return 0
        session.commit()
        for rec in result.stored:
            print(f"  {rec.priority:5.2f}  #{rec.id} {rec.action}")
        for rejection in result.rejected:
            print(f"  rejected  {rejection.action} ({rejection.reason})")
    replaced = f", replaced {result.replaced} from earlier today" if result.replaced else ""
    print(f"Stored {len(result.stored)} recommendations{replaced}")
    # Every proposal rejected means the model did not cite the data: flag the run.
    return 1 if not result.stored else 0


def report() -> int:
    """Build the weekly summary for the notifications page (guide Step 6)."""
    from datetime import date
    from pathlib import Path

    from sqlalchemy.orm import Session

    from scout_ai.config import get_settings
    from scout_ai.db.session import get_engine
    from scout_ai.reports.weekly import build_weekly_report, render_markdown, save_summary

    today = date.today()
    with Session(get_engine()) as session, session.begin():
        weekly = build_weekly_report(session, today)
        markdown = render_markdown(weekly)
        summary = save_summary(session, weekly, markdown)
        print(f"Stored summary {summary.id} ({summary.signal_count} signals)")
    path = Path(get_settings().report_dir) / f"weekly-{today:%Y-%m-%d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    print(f"Wrote {path}")
    return 0


COMMANDS: dict[str, Callable[[], int]] = {
    "db-setup": db_setup,
    "collect": collect,
    "fetch": fetch,
    "load": load,
    "analyze": analyze,
    "recommend": recommend,
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
