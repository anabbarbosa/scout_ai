from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from scout_ai.db.models import (
    Campaign,
    Competitor,
    DealCompetition,
    DealOutcome,
    FunnelMetric,
    MarketingSpend,
    Region,
)
from scout_ai.db.setup import setup_database
from scout_ai.demo.load import DemoDatasetError, load_dataset
from scout_ai.demo.schema import (
    GENERATOR_VERSION,
    MANIFEST,
    SCHEMAS,
    TABLES,
    Manifest,
    parquet_path,
    sha256,
)

ROWS: dict[str, list[dict[str, Any]]] = {
    "funnel_metrics": [
        {
            "period": date(2026, 1, 1),
            "region": "brazil",
            "channel": "Paid Search",
            "campaign": "Campanha Aurora",
            "leads": 120,
            "mqls": 40,
            "sqls": 12,
            "opportunities": 6,
            "deals_won": 2,
            "revenue": Decimal("15300.50"),
        },
        {
            "period": date(2026, 2, 1),
            "region": "emea",
            "channel": "Organic",
            "campaign": "",
            "leads": 30,
            "mqls": 5,
            "sqls": 1,
            "opportunities": 0,
            "deals_won": 0,
            "revenue": Decimal("0.00"),
        },
    ],
    "deals_competition": [
        {
            "deal_id": "demo-0001",
            "competitor": "LabWare",
            "outcome": "won",
            "amount": Decimal("42000.00"),
            "closed_at": date(2026, 3, 15),
        },
        {
            "deal_id": "demo-0002",
            "competitor": "STARLIMS",
            "outcome": "open",
            "amount": None,
            "closed_at": None,
        },
    ],
    "campaigns": [
        {
            "name": "Campanha Aurora",
            "channel": "Paid Search",
            "first_mql_at": date(2026, 1, 5),
            "last_mql_at": date(2026, 1, 28),
        },
    ],
    "marketing_spend": [
        {"period": date(2026, 1, 1), "region": "brazil", "amount": Decimal("8000.00")},
        {"period": date(2026, 1, 1), "region": "emea", "amount": Decimal("5500.25")},
    ],
}

Contents = dict[str, list[tuple[Any, ...]]]


def write_dataset(directory: Path, rows: dict[str, list[dict[str, Any]]]) -> Manifest:
    directory.mkdir(parents=True, exist_ok=True)
    for table in TABLES:
        pq.write_table(
            pa.Table.from_pylist(rows[table], schema=SCHEMAS[table]),
            parquet_path(directory, table),
        )
    manifest = Manifest(
        generated_at="2026-11-03T00:00:00+00:00",
        seed=42,
        generator_version=GENERATOR_VERSION,
        row_counts={table: len(rows[table]) for table in TABLES},
        sha256={table: sha256(parquet_path(directory, table)) for table in TABLES},
    )
    manifest.write(directory)
    return manifest


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    url = f"sqlite:///{(tmp_path / 'scout.db').as_posix()}"
    setup_database(url)
    engine = create_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    directory = tmp_path / "demo"
    write_dataset(directory, ROWS)
    return directory


def load(engine: Engine, directory: Path) -> dict[str, int]:
    with Session(engine) as session:
        return load_dataset(directory, session)


def contents(engine: Engine) -> Contents:
    with Session(engine) as session:
        return {
            "funnel_metrics": [
                (
                    r.period,
                    r.region,
                    r.channel,
                    r.campaign,
                    r.leads,
                    r.mqls,
                    r.sqls,
                    r.opportunities,
                    r.deals_won,
                    r.revenue,
                )
                for r in session.scalars(select(FunnelMetric).order_by(FunnelMetric.period))
            ],
            "deals_competition": [
                (r.deal_id, r.competitor.name, r.competitor_id, r.outcome, r.amount, r.closed_at)
                for r in session.scalars(select(DealCompetition).order_by(DealCompetition.deal_id))
            ],
            "campaigns": [
                (r.name, r.channel, r.first_mql_at, r.last_mql_at)
                for r in session.scalars(select(Campaign).order_by(Campaign.name))
            ],
            "marketing_spend": [
                (r.period, r.region, r.amount)
                for r in session.scalars(
                    select(MarketingSpend).order_by(MarketingSpend.period, MarketingSpend.region)
                )
            ],
        }


def competitor_id(engine: Engine, name: str) -> int:
    with Session(engine) as session:
        value = session.scalar(select(Competitor.id).where(Competitor.name == name))
    assert value is not None
    return value


def test_loads_rows_and_values(engine: Engine, dataset: Path) -> None:
    assert load(engine, dataset) == {table: len(ROWS[table]) for table in TABLES}
    data = contents(engine)
    assert data["funnel_metrics"][0] == (
        date(2026, 1, 1),
        Region.BRAZIL,
        "Paid Search",
        "Campanha Aurora",
        120,
        40,
        12,
        6,
        2,
        Decimal("15300.50"),
    )
    assert data["deals_competition"] == [
        (
            "demo-0001",
            "LabWare",
            competitor_id(engine, "LabWare"),
            DealOutcome.WON,
            Decimal("42000.00"),
            date(2026, 3, 15),
        ),
        ("demo-0002", "STARLIMS", competitor_id(engine, "STARLIMS"), DealOutcome.OPEN, None, None),
    ]
    assert data["campaigns"] == [
        ("Campanha Aurora", "Paid Search", date(2026, 1, 5), date(2026, 1, 28))
    ]
    assert data["marketing_spend"] == [
        (date(2026, 1, 1), Region.BRAZIL, Decimal("8000.00")),
        (date(2026, 1, 1), Region.EMEA, Decimal("5500.25")),
    ]


def test_loading_twice_gives_same_contents(engine: Engine, dataset: Path) -> None:
    first = load(engine, dataset)
    before = contents(engine)
    assert load(engine, dataset) == first
    assert contents(engine) == before


def test_existing_rows_are_replaced(engine: Engine, dataset: Path) -> None:
    with Session(engine) as session, session.begin():
        session.add(MarketingSpend(period=date(2020, 1, 1), region=Region.APAC, amount=Decimal(1)))
        session.add(Campaign(name="Old campaign", channel="Email"))
        session.add(
            DealCompetition(
                deal_id="old-1",
                competitor_id=competitor_id(engine, "Clinisys"),
                outcome=DealOutcome.LOST,
            )
        )
    load(engine, dataset)
    assert contents(engine) == expected_contents(engine, dataset)


def expected_contents(engine: Engine, dataset: Path) -> Contents:
    """Contents after loading `dataset` into a fresh database."""
    fresh_url = f"sqlite:///{(dataset.parent / 'fresh.db').as_posix()}"
    setup_database(fresh_url)
    fresh = create_engine(fresh_url)
    try:
        load(fresh, dataset)
        return contents(fresh)
    finally:
        fresh.dispose()


def _tamper(directory: Path) -> None:
    path = parquet_path(directory, "marketing_spend")
    rows = [{**ROWS["marketing_spend"][0], "amount": Decimal("9999.00")}]
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMAS["marketing_spend"]), path)


def _wrong_row_count(directory: Path) -> None:
    manifest = Manifest.read(directory)
    replace(manifest, row_counts={**manifest.row_counts, "campaigns": 5}).write(directory)


def _missing_file(directory: Path) -> None:
    parquet_path(directory, "campaigns").unlink()


def _missing_manifest(directory: Path) -> None:
    (directory / MANIFEST).unlink()


def _wrong_schema(directory: Path) -> None:
    # Amount written as a float: rewrite the manifest so only the schema check can fail.
    path = parquet_path(directory, "marketing_spend")
    period, region, _ = SCHEMAS["marketing_spend"]
    schema = pa.schema([period, region, pa.field("amount", pa.float64())])
    rows = [{**row, "amount": float(row["amount"])} for row in ROWS["marketing_spend"]]
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    manifest = Manifest.read(directory)
    replace(manifest, sha256={**manifest.sha256, "marketing_spend": sha256(path)}).write(directory)


@pytest.mark.parametrize(
    ("break_dataset", "message"),
    [
        (_tamper, "SHA-256"),
        (_wrong_row_count, "campaigns.parquet: 1 rows"),
        (_missing_file, "campaigns.parquet: not found"),
        (_missing_manifest, "manifest.json: not found"),
        (_wrong_schema, "marketing_spend.parquet: schema differs"),
    ],
)
def test_invalid_dataset_leaves_database_untouched(
    engine: Engine,
    dataset: Path,
    tmp_path: Path,
    break_dataset: Callable[[Path], None],
    message: str,
) -> None:
    load(engine, dataset)
    before = contents(engine)

    broken = tmp_path / "broken"
    write_dataset(broken, {**ROWS, "campaigns": [{**ROWS["campaigns"][0], "name": "Other"}]})
    break_dataset(broken)
    with pytest.raises(DemoDatasetError, match=message):
        load(engine, broken)
    assert contents(engine) == before


def test_unknown_competitor_rolls_back(engine: Engine, dataset: Path, tmp_path: Path) -> None:
    load(engine, dataset)
    before = contents(engine)

    broken = tmp_path / "broken"
    deal = {**ROWS["deals_competition"][0], "competitor": "Acme LIMS"}
    write_dataset(broken, {**ROWS, "deals_competition": [deal], "campaigns": []})
    with pytest.raises(DemoDatasetError, match=r"Acme LIMS.*scout db-setup"):
        load(engine, broken)
    assert contents(engine) == before


def test_unknown_region_is_rejected(engine: Engine, tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    spend = [{**ROWS["marketing_spend"][0], "region": "mars"}]
    write_dataset(broken, {**ROWS, "marketing_spend": spend})
    with pytest.raises(DemoDatasetError, match="mars"):
        load(engine, broken)
    assert contents(engine)["marketing_spend"] == []


def test_constraint_violation_rolls_back(engine: Engine, dataset: Path, tmp_path: Path) -> None:
    # Fails on the last insert, after the tables were emptied: the delete must be rolled back.
    load(engine, dataset)
    before = contents(engine)

    broken = tmp_path / "broken"
    spend = [ROWS["marketing_spend"][0], ROWS["marketing_spend"][0]]
    write_dataset(broken, {**ROWS, "marketing_spend": spend})
    with pytest.raises(DemoDatasetError, match="constraint"):
        load(engine, broken)
    assert contents(engine) == before
