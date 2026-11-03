"""Load the demo dataset in data/demo/ into the database: `scout load` (guide Step 5).

The files are checked against manifest.json before the database is touched. The four
internal-data tables are then replaced in one transaction, so a failed load leaves the
database as it was and running it twice gives the same content.
"""

import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from scout_ai.db.base import Base
from scout_ai.db.models import (
    Campaign,
    Competitor,
    DealCompetition,
    DealOutcome,
    FunnelMetric,
    MarketingSpend,
    Region,
)
from scout_ai.demo.schema import MANIFEST, SCHEMAS, TABLES, Manifest, parquet_path, sha256

MODELS: dict[str, type[Base]] = {
    "funnel_metrics": FunnelMetric,
    "deals_competition": DealCompetition,
    "campaigns": Campaign,
    "marketing_spend": MarketingSpend,
}

Rows = list[dict[str, Any]]


class DemoDatasetError(ValueError):
    pass


def read_manifest(directory: Path) -> Manifest:
    path = directory / MANIFEST
    if not path.is_file():
        raise DemoDatasetError(f"{path}: not found; run `scout fetch` or `git pull` first")
    try:
        return Manifest.read(directory)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DemoDatasetError(f"{path}: not a valid manifest ({exc})") from exc


def read_table(directory: Path, table: str, manifest: Manifest) -> Rows:
    """Read one Parquet file after checking its hash, schema and row count."""
    path = parquet_path(directory, table)
    if not path.is_file():
        raise DemoDatasetError(f"{path}: not found")
    expected_sha = manifest.sha256.get(table)
    if expected_sha is None or table not in manifest.row_counts:
        raise DemoDatasetError(f"{directory / MANIFEST}: no entry for {table}")
    if sha256(path) != expected_sha:
        raise DemoDatasetError(f"{path}: SHA-256 does not match {MANIFEST}")

    data = pq.read_table(path)
    if not data.schema.equals(SCHEMAS[table], check_metadata=False):
        raise DemoDatasetError(
            f"{path}: schema differs from the expected one\n"
            f"expected:\n{SCHEMAS[table]}\nfound:\n{data.schema}"
        )
    if data.num_rows != manifest.row_counts[table]:
        raise DemoDatasetError(
            f"{path}: {data.num_rows} rows, {MANIFEST} says {manifest.row_counts[table]}"
        )
    rows: Rows = data.to_pylist()
    return rows


def _parse_enums(path: Path, rows: Rows) -> None:
    """Turn `region` and `outcome` strings into enum members, rejecting unknown values."""
    for row in rows:
        try:
            if "region" in row:
                row["region"] = Region(row["region"])
            if "outcome" in row:
                row["outcome"] = DealOutcome(row["outcome"])
        except ValueError as exc:
            raise DemoDatasetError(f"{path}: {exc}") from exc


def read_dataset(directory: Path) -> dict[str, Rows]:
    """Read and check every table of the dataset; nothing touches the database."""
    manifest = read_manifest(directory)
    dataset = {table: read_table(directory, table, manifest) for table in TABLES}
    for table, rows in dataset.items():
        _parse_enums(parquet_path(directory, table), rows)
    return dataset


def _resolve_competitors(session: Session, rows: Rows) -> Rows:
    ids = {name: id_ for name, id_ in session.execute(select(Competitor.name, Competitor.id))}
    missing = sorted({row["competitor"] for row in rows} - ids.keys())
    if missing:
        raise DemoDatasetError(
            f"unknown competitors {', '.join(missing)}; run `scout db-setup` to seed them"
        )
    return [
        {
            **{k: v for k, v in row.items() if k != "competitor"},
            "competitor_id": ids[row["competitor"]],
        }
        for row in rows
    ]


def load_dataset(directory: Path, session: Session) -> dict[str, int]:
    """Replace the internal-data tables with the dataset in `directory`. Returns rows per table.

    `session` must not be in a transaction: this function commits, or rolls back on error.
    """
    dataset = read_dataset(directory)
    try:
        with session.begin():
            dataset["deals_competition"] = _resolve_competitors(
                session, dataset["deals_competition"]
            )
            for table in TABLES:
                model = MODELS[table]
                session.execute(delete(model))
                if dataset[table]:
                    session.execute(insert(model), dataset[table])
    except IntegrityError as exc:
        raise DemoDatasetError(f"dataset violates a database constraint: {exc.orig}") from exc
    return {table: len(rows) for table, rows in dataset.items()}
