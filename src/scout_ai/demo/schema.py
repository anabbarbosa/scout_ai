"""File contract of the demo dataset in data/demo/, shared by synthesize.py and load.py.

One Parquet file per table, plus manifest.json. Columns mirror the ORM tables without the
surrogate `id` and timestamps; competitors are referenced by name (resolved to IDs on load)
and regions by their `Region` value.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa

GENERATOR_VERSION = "1"
MANIFEST = "manifest.json"

MONEY = pa.decimal128(14, 2)

SCHEMAS: dict[str, pa.Schema] = {
    "funnel_metrics": pa.schema(
        [
            pa.field("period", pa.date32(), nullable=False),  # first day of the month
            pa.field("region", pa.string(), nullable=False),  # Region value
            pa.field("channel", pa.string(), nullable=False),
            pa.field("campaign", pa.string(), nullable=False),  # "" when none
            pa.field("leads", pa.int64(), nullable=False),
            pa.field("mqls", pa.int64(), nullable=False),
            pa.field("sqls", pa.int64(), nullable=False),
            pa.field("opportunities", pa.int64(), nullable=False),
            pa.field("deals_won", pa.int64(), nullable=False),
            pa.field("revenue", MONEY, nullable=False),
        ]
    ),
    "deals_competition": pa.schema(
        [
            pa.field("deal_id", pa.string(), nullable=False),  # synthetic: demo-0001, ...
            pa.field("competitor", pa.string(), nullable=False),  # Competitor.name from seed.py
            pa.field("outcome", pa.string(), nullable=False),  # DealOutcome value
            pa.field("amount", MONEY, nullable=True),
            pa.field("closed_at", pa.date32(), nullable=True),
        ]
    ),
    "campaigns": pa.schema(
        [
            pa.field("name", pa.string(), nullable=False),  # synthetic; matches funnel_metrics
            pa.field("channel", pa.string(), nullable=False),
            pa.field("first_mql_at", pa.date32(), nullable=True),
            pa.field("last_mql_at", pa.date32(), nullable=True),
        ]
    ),
    "marketing_spend": pa.schema(
        [
            pa.field("period", pa.date32(), nullable=False),
            pa.field("region", pa.string(), nullable=False),
            pa.field("amount", MONEY, nullable=False),
        ]
    ),
}

TABLES = tuple(SCHEMAS)


def parquet_path(directory: Path, table: str) -> Path:
    return directory / f"{table}.parquet"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Manifest:
    generated_at: str  # ISO 8601, UTC
    seed: int
    generator_version: str
    row_counts: dict[str, int]
    sha256: dict[str, str] = field(default_factory=dict)  # per table file

    def write(self, directory: Path) -> None:
        text = json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"
        (directory / MANIFEST).write_text(text, encoding="utf-8")

    @classmethod
    def read(cls, directory: Path) -> Manifest:
        data: dict[str, Any] = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
        return cls(**data)
