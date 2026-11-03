import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scout_ai.db.models import DealOutcome, Region
from scout_ai.db.seed import COMPETITORS
from scout_ai.demo.schema import GENERATOR_VERSION, SCHEMAS, TABLES, Manifest, parquet_path, sha256
from scout_ai.demo.synthesize import Check, compare, synthesize, write_dataset
from scout_ai.integrations.hubspot import DealRow
from scout_ai.integrations.marketing_csv import MqlRow, SpendRow

SEED = 42
REGIONS = (Region.NORTH_AMERICA, Region.BRAZIL, Region.EMEA)
# HubSpot spelling -> Marketing export spelling, with each channel's real campaigns.
CHANNELS = {
    "PAID_SEARCH": ("Paid Search", ("real-google-ads", "real-bing-ads")),
    "ORGANIC_SEARCH": ("Organic Search", ("",)),
    "SOCIAL_MEDIA": ("Social Media", ("real-linkedin-lims",)),
}
SMALL_CAMPAIGN = "real-tiny-webinar"  # fewer than 10 records: merged
UNKNOWN = "Unknown Corp"  # not a seed competitor: dropped
START = date(2025, 1, 1)


def _deals() -> list[DealRow]:
    rng = random.Random(1)
    labels = ["LabWare", "labvantage", "Clinisys"] * 30 + ["STARLIMS"] * 3 + ["CloudLIMS"] * 2
    deals: list[DealRow] = []
    for i in range(400):
        hub_channel = rng.choice(sorted(CHANNELS))
        campaign = rng.choice(CHANNELS[hub_channel][1])
        created = START + timedelta(days=rng.randint(0, 330))
        outcome = rng.choices(list(DealOutcome), weights=(3, 3, 4))[0]
        closed = created + timedelta(days=rng.randint(5, 90)) if outcome != "open" else None
        competitors: tuple[str, ...] = ()
        if i < len(labels):
            competitors = (labels[i],)
            if i % 7 == 0:
                competitors += ("Clinisys",)
        elif i < len(labels) + 5:
            competitors = (UNKNOWN,)
        deals.append(
            DealRow(
                deal_id=str(9_000_000 + i * 13),
                pipeline="47550223",
                stage="closedwon" if outcome is DealOutcome.WON else "appointmentscheduled",
                outcome=outcome,
                amount=Decimal(rng.randint(5_000, 200_000)) / 100 * 10 if i % 9 else None,
                created_at=created,
                closed_at=closed,
                region=rng.choice(REGIONS),
                channel=hub_channel,
                campaign=campaign,
                competitors=competitors,
            )
        )
    return deals


def _mqls() -> list[MqlRow]:
    rng = random.Random(2)
    mqls: list[MqlRow] = []
    for _ in range(900):
        channel, campaigns = CHANNELS[rng.choice(sorted(CHANNELS))]
        mqls.append(
            MqlRow(
                mql_date=START + timedelta(days=rng.randint(0, 330)),
                region=rng.choice(REGIONS),
                channel=channel,
                campaign=rng.choice(campaigns),
            )
        )
    mqls += [
        MqlRow(START + timedelta(days=d), Region.BRAZIL, "Paid Search", SMALL_CAMPAIGN)
        for d in (10, 40, 70)
    ]
    return mqls


def _spend() -> list[SpendRow]:
    rng = random.Random(3)
    base = {Region.NORTH_AMERICA: 50_000, Region.BRAZIL: 20_000}
    return [
        SpendRow(date(2025, month, 1), region, Decimal(rng.randint(80, 120) * amount) / 100)
        for month in range(1, 13)
        for region, amount in base.items()
    ]


DEALS = _deals()
MQLS = _mqls()
SPEND = _spend()


@pytest.fixture(scope="module")
def tables() -> dict[str, pa.Table]:
    return synthesize(DEALS, SPEND, MQLS, seed=SEED)


def _column(tables: dict[str, pa.Table], table: str, column: str) -> list[Any]:
    values: list[Any] = tables[table].column(column).to_pylist()
    return values


def test_tables_match_the_file_contract(tables: dict[str, pa.Table]) -> None:
    assert tuple(tables) == TABLES
    for name in TABLES:
        assert tables[name].schema.equals(SCHEMAS[name])
        assert tables[name].num_rows > 0


def test_same_input_and_seed_give_the_same_tables(tables: dict[str, pa.Table]) -> None:
    rng = random.Random(7)
    deals, spend, mqls = list(DEALS), list(SPEND), list(MQLS)
    for rows in (deals, spend, mqls):
        rng.shuffle(rows)
    again = synthesize(DEALS, SPEND, MQLS, seed=SEED)
    shuffled = synthesize(deals, spend, mqls, seed=SEED)
    for name in TABLES:
        assert again[name].equals(tables[name])
        assert shuffled[name].equals(tables[name])
    other = synthesize(DEALS, SPEND, MQLS, seed=SEED + 1)
    assert not other["marketing_spend"].equals(tables["marketing_spend"])


def test_no_real_value_reaches_the_output(tables: dict[str, pa.Table]) -> None:
    real_campaigns = {d.campaign for d in DEALS} | {m.campaign for m in MQLS}
    real_campaigns.discard("")
    names = set(_column(tables, "campaigns", "name"))
    names |= set(_column(tables, "funnel_metrics", "campaign"))
    assert not names & real_campaigns
    assert not set(_column(tables, "deals_competition", "deal_id")) & {d.deal_id for d in DEALS}
    assert all(str(i).startswith("demo-") for i in _column(tables, "deals_competition", "deal_id"))
    amounts = set(_column(tables, "deals_competition", "amount")) - {None}
    assert amounts
    assert not amounts & {d.amount for d in DEALS}
    assert not set(_column(tables, "marketing_spend", "amount")) & {s.amount for s in SPEND}


def test_channels_join_between_sources(tables: dict[str, pa.Table]) -> None:
    assert set(_column(tables, "funnel_metrics", "channel")) == {c for c, _ in CHANNELS.values()}


def test_small_campaign_is_merged(tables: dict[str, pa.Table]) -> None:
    campaigns = dict(
        zip(
            _column(tables, "campaigns", "name"),
            _column(tables, "campaigns", "channel"),
            strict=True,
        )
    )
    assert campaigns["Outras campanhas (Paid Search)"] == "Paid Search"
    assert "" not in campaigns
    # Two large Paid Search campaigns and one Social Media one, plus the merged group.
    assert len(campaigns) == 4
    funnel_names = set(_column(tables, "funnel_metrics", "campaign")) - {""}
    assert funnel_names == set(campaigns)
    first = _column(tables, "campaigns", "first_mql_at")
    last = _column(tables, "campaigns", "last_mql_at")
    assert all(f <= la for f, la in zip(first, last, strict=True))


def test_competitors_are_seed_names_and_unknown_labels_are_dropped(
    tables: dict[str, pa.Table],
) -> None:
    competitors = set(_column(tables, "deals_competition", "competitor"))
    assert competitors <= {c.name for c in COMPETITORS}
    assert {"LabWare", "LabVantage", "Clinisys"} <= competitors
    with_seed_competitor = sum(
        any(c.casefold() != UNKNOWN.casefold() for c in d.competitors) for d in DEALS
    )
    assert len(set(_column(tables, "deals_competition", "deal_id"))) == with_seed_competitor


def test_synthetic_rates_stay_within_five_points(tables: dict[str, pa.Table]) -> None:
    checks = compare(DEALS, SPEND, MQLS, tables)
    metrics = {c.metric for c in checks}
    assert "Opportunities -> won" in metrics
    assert "MQLs -> opportunities" in metrics
    assert "Win rate vs LabWare" in metrics
    assert "Win rate vs Rare competitors (pooled)" in metrics
    assert "Spend share brazil" in metrics
    assert [c for c in checks if not c.ok] == []


def test_check_tolerance() -> None:
    assert Check("x", 50.0, 55.0).ok
    assert not Check("x", 50.0, 55.5).ok
    assert Check("x", 50.0, 44.0).diff_pp == -6.0
    assert Check("x", 50.0, 62.5, tolerance_pp=15.0, must_differ=True).ok
    assert not Check("x", 50.0, 50.0, tolerance_pp=15.0, must_differ=True).ok


def _win_rate_checks(deals: list[DealRow], seed: int) -> list[Check]:
    tables = synthesize(deals, SPEND, MQLS, seed=seed)
    return [c for c in compare(deals, SPEND, MQLS, tables) if c.metric.startswith("Win rate")]


@pytest.mark.parametrize("seed", range(10))
def test_no_competitor_win_rate_equals_the_real_one(seed: int) -> None:
    checks = _win_rate_checks(DEALS, seed)
    assert checks
    assert all(c.diff_pp != 0 and c.ok for c in checks), checks


@pytest.mark.parametrize("seed", range(10))
def test_win_rates_differ_even_with_few_closed_deals(seed: int) -> None:
    # Like the real data: a competitor with 8 closed deals, where one flip is 12.5 pp.
    few = [d for d in DEALS if not d.competitors or d.competitors[0] != "labvantage"]
    labvantage = [d for d in DEALS if d.competitors and d.competitors[0] == "labvantage"]
    # 12 deals keep it above MIN_GROUP (not pooled), 8 of them closed.
    closed = [d for d in labvantage if d.outcome is not DealOutcome.OPEN][:8]
    still_open = [d for d in labvantage if d.outcome is DealOutcome.OPEN][:4]
    assert len(closed) == 8 and len(still_open) == 4
    checks = _win_rate_checks(few + closed + still_open, seed)
    assert any(c.metric == "Win rate vs LabVantage" for c in checks)
    assert all(c.diff_pp != 0 and c.ok for c in checks), checks


def test_write_dataset_matches_manifest(tables: dict[str, pa.Table], tmp_path: Path) -> None:
    directory = tmp_path / "demo"
    manifest = write_dataset(tables, directory, seed=SEED)
    assert Manifest.read(directory) == manifest
    assert manifest.seed == SEED
    assert manifest.generator_version == GENERATOR_VERSION
    assert manifest.generated_at.endswith("+00:00")
    for name in TABLES:
        path = parquet_path(directory, name)
        assert manifest.sha256[name] == sha256(path)
        assert manifest.row_counts[name] == pq.read_table(path).num_rows
        assert pq.read_table(path).schema.equals(SCHEMAS[name])
