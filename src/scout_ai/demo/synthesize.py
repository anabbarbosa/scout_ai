"""Turn real deals, spend and MQLs into the synthetic demo dataset (guide Step 5).

Real records stay in memory: `synthesize` keeps their proportions and shape but never their
values (campaign names, deal IDs, amounts, spend), and `compare` reports how close the
synthetic rates are to the real ones so `scout fetch` can print it. Same input and seed give
the same tables, whatever the input order.
"""

import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from faker import Faker

from scout_ai.db.models import DealOutcome
from scout_ai.db.seed import COMPETITORS
from scout_ai.demo.schema import (
    GENERATOR_VERSION,
    SCHEMAS,
    TABLES,
    Manifest,
    parquet_path,
    sha256,
)
from scout_ai.integrations.hubspot import DealRow
from scout_ai.integrations.marketing_csv import MqlRow, SpendRow

MIN_GROUP = 10  # groups with fewer real records are merged or pooled
TOLERANCE_PP = 5.0  # allowed gap between real and synthetic rates, in percentage points
# Win rates per competitor rest on few closed deals, so one flipped outcome can move them
# more than TOLERANCE_PP. They must differ from the real rate, within this or one flip.
COMPETITOR_TOLERANCE_PP = 15.0
DATE_JITTER_DAYS = 7
CLOSE_JITTER_DAYS = 3
AMOUNT_JITTER = 0.10  # multiplicative, on bootstrapped amounts
SPEND_SCALE = (0.85, 1.15)  # one global factor
SPEND_NOISE = 0.04  # per period x region cell
OUTCOME_FLIP = 0.05  # share of closed deals whose outcome is flipped (won <-> lost)
OUTCOME_DRIFT = 0.04  # largest change those flips may cause in any win rate
MQL_DROP = 0.03
MQL_DUPLICATE = 0.03
RARE = "*rare*"  # stratum marker for pooled rare competitors
CENT = Decimal("0.01")

_SEED_NAMES = {c.name.casefold(): c.name for c in COMPETITORS}


@dataclass(frozen=True)
class Check:
    metric: str
    real: float  # percent
    synthetic: float  # percent
    tolerance_pp: float = TOLERANCE_PP
    must_differ: bool = False  # the synthetic rate may not equal the real one

    @property
    def diff_pp(self) -> float:
        return self.synthetic - self.real

    @property
    def ok(self) -> bool:
        if self.must_differ and abs(self.diff_pp) < 1e-9:
            return False
        return abs(self.diff_pp) <= self.tolerance_pp + 1e-9


@dataclass(frozen=True)
class _Deal:
    region: str
    channel: str
    campaign: str  # synthetic name
    outcome: DealOutcome
    amount: Decimal | None
    created_at: date
    closed_at: date | None
    competitors: tuple[str, ...]  # seed names, sorted


@dataclass(frozen=True)
class _Mql:
    mql_date: date
    region: str
    channel: str
    campaign: str  # synthetic name


# --- shared helpers (also used by compare) ---


def _channel_lookup(mqls: Iterable[MqlRow]) -> dict[str, str]:
    """MQL channel spellings keyed by their case-folded form."""
    return {m.channel.casefold(): m.channel for m in sorted(mqls, key=lambda m: m.channel)}


def _channel(raw: str, lookup: dict[str, str]) -> str:
    """HubSpot's "PAID_SEARCH" -> the MQL export's "Paid Search" (title case when unknown)."""
    words = raw.replace("_", " ").split()
    spaced = " ".join(words)
    return lookup.get(spaced.casefold()) or " ".join(w.capitalize() for w in words)


def _seed_competitors(deal: DealRow) -> tuple[str, ...]:
    """Seed competitor names of a deal; labels not in the seed are dropped."""
    return tuple(
        sorted(
            {_SEED_NAMES[k] for label in deal.competitors if (k := label.casefold()) in _SEED_NAMES}
        )
    )


def _rare_competitors(deals: Sequence[DealRow]) -> set[str]:
    counts = Counter(name for d in deals for name in _seed_competitors(d))
    return {name for name, n in counts.items() if n < MIN_GROUP}


def _month(day: date) -> date:
    return day.replace(day=1)


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def _pct(part: float, whole: float) -> float:
    return 100.0 * part / whole if whole else 0.0


# --- synthesis ---


def _jitter_date(rng: random.Random, day: date, low: date, high: date, days: int) -> date:
    shifted = day + timedelta(days=rng.randint(-days, days))
    return min(max(shifted, low), high)


def _avoid(value: Decimal, real: set[Decimal]) -> Decimal:
    """Nudge a synthetic value by cents until it differs from every real value."""
    while value in real:
        value += CENT
    return value


def _campaign_names(
    deals: Sequence[DealRow], mqls: Sequence[MqlRow], lookup: dict[str, str], seed: int
) -> dict[tuple[str, str], str]:
    """Real (channel, campaign) -> fake campaign name; small campaigns merge per channel."""
    counts: Counter[tuple[str, str]] = Counter()
    for d in deals:
        counts[(_channel(d.channel, lookup), d.campaign)] += 1
    for m in mqls:
        counts[(m.channel, m.campaign)] += 1

    real_names = {campaign.casefold() for _, campaign in counts}
    fake = Faker("pt_BR")
    fake.seed_instance(seed)
    used: set[str] = set()
    names: dict[tuple[str, str], str] = {}
    for channel, campaign in sorted(counts):
        if not campaign:
            names[(channel, campaign)] = ""
        elif counts[(channel, campaign)] < MIN_GROUP:
            names[(channel, campaign)] = f"Outras campanhas ({channel or 'sem canal'})"
    used.update(names.values())
    for key in sorted(counts):
        if key in names:
            continue
        while True:
            name = fake.catch_phrase()
            if name not in used and name.casefold() not in real_names:
                break
        used.add(name)
        names[key] = name
    return names


def _stratum(competitors: tuple[str, ...], rare: set[str]) -> tuple[str, ...]:
    return tuple(sorted({RARE if c in rare else c for c in competitors}))


def _outcomes(rng: random.Random, deals: Sequence[DealRow], rare: set[str]) -> list[DealOutcome]:
    """Outcomes shuffled within each competitor stratum, then a few won/lost flips.

    Rare competitors share one stratum, so their outcomes come from the pooled rate. A flip
    is kept only while every affected win rate (overall and per competitor group) stays
    within OUTCOME_DRIFT of the real one.
    """
    strata: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for i, deal in enumerate(deals):
        strata[_stratum(_seed_competitors(deal), rare)].append(i)

    result: list[DealOutcome] = [DealOutcome.OPEN] * len(deals)
    for key in sorted(strata):
        idx = strata[key]
        outcomes = [deals[i].outcome for i in idx]
        rng.shuffle(outcomes)
        for i, outcome in zip(idx, outcomes, strict=True):
            result[i] = outcome

    groups = [(*_stratum(_seed_competitors(d), rare), "") for d in deals]  # "" = all deals
    real_won: Counter[str] = Counter()
    closed: Counter[str] = Counter()
    for deal, keys in zip(deals, groups, strict=True):
        for g in keys:
            closed[g] += deal.outcome is not DealOutcome.OPEN
            real_won[g] += deal.outcome is DealOutcome.WON
    won = Counter(real_won)
    candidates = [i for i, o in enumerate(result) if o is not DealOutcome.OPEN]
    budget = round(OUTCOME_FLIP * len(candidates))
    for i in rng.sample(candidates, len(candidates)):
        if budget == 0:
            break
        delta = -1 if result[i] is DealOutcome.WON else 1
        if all(abs(won[g] + delta - real_won[g]) <= OUTCOME_DRIFT * closed[g] for g in groups[i]):
            for g in groups[i]:
                won[g] += delta
            result[i] = DealOutcome.LOST if delta < 0 else DealOutcome.WON
            budget -= 1

    # No competitor group may keep its real win count, or the demo would show its real rate.
    # Flips of deals with several competitors move other groups too, so repeat a few passes.
    competitor_groups = sorted(g for g in closed if g and closed[g])
    for _ in range(5):
        same = [g for g in competitor_groups if won[g] == real_won[g]]
        if not same:
            break
        for g in same:
            if won[g] != real_won[g]:
                continue
            deltas = [d for d, ok in ((1, won[g] < closed[g]), (-1, won[g] > 0)) if ok]
            delta = rng.choice(deltas)
            source = DealOutcome.LOST if delta > 0 else DealOutcome.WON
            options = [i for i in range(len(deals)) if g in groups[i] and result[i] is source]
            # Prefer deals against this competitor group alone.
            alone = [i for i in options if len(groups[i]) == 2]
            i = rng.choice(alone or options)
            for affected in groups[i]:
                won[affected] += delta
            result[i] = DealOutcome.WON if delta > 0 else DealOutcome.LOST
    return result


def _synthetic_deals(
    rng: random.Random,
    deals: Sequence[DealRow],
    lookup: dict[str, str],
    campaigns: dict[tuple[str, str], str],
) -> list[_Deal]:
    if not deals:
        return []
    rare = _rare_competitors(deals)
    rare_pool = sorted(c for d in deals for c in _seed_competitors(d) if c in rare)
    outcomes = _outcomes(rng, deals, rare)
    amounts = sorted(d.amount for d in deals if d.amount is not None)
    real_amounts = set(amounts)
    durations = sorted((d.closed_at - d.created_at).days for d in deals if d.closed_at is not None)
    first = min(d.created_at for d in deals)
    last = max(d.created_at for d in deals)
    last_close = max((d.closed_at for d in deals if d.closed_at), default=last)

    result: list[_Deal] = []
    for deal, outcome in zip(deals, outcomes, strict=True):
        channel = _channel(deal.channel, lookup)
        created = _jitter_date(rng, deal.created_at, first, last, DATE_JITTER_DAYS)
        closed: date | None = None
        if outcome is not DealOutcome.OPEN:
            days = rng.choice(durations) + rng.randint(-CLOSE_JITTER_DAYS, CLOSE_JITTER_DAYS)
            closed = min(created + timedelta(days=max(days, 0)), max(last_close, created))
        amount: Decimal | None = None
        if deal.amount is not None:
            factor = Decimal(str(round(rng.uniform(1 - AMOUNT_JITTER, 1 + AMOUNT_JITTER), 4)))
            amount = _avoid(_money(rng.choice(amounts) * factor), real_amounts)
        competitors = {rng.choice(rare_pool) if c in rare else c for c in _seed_competitors(deal)}
        result.append(
            _Deal(
                region=deal.region.value,
                channel=channel,
                campaign=campaigns[(channel, deal.campaign)],
                outcome=outcome,
                amount=amount,
                created_at=created,
                closed_at=closed,
                competitors=tuple(sorted(competitors)),
            )
        )
    return result


def _synthetic_mqls(
    rng: random.Random, mqls: Sequence[MqlRow], campaigns: dict[tuple[str, str], str]
) -> list[_Mql]:
    if not mqls:
        return []
    first = min(m.mql_date for m in mqls)
    last = max(m.mql_date for m in mqls)
    result: list[_Mql] = []
    for m in mqls:
        draw = rng.random()
        copies = 0 if draw < MQL_DROP else 2 if draw > 1 - MQL_DUPLICATE else 1
        for _ in range(copies):
            result.append(
                _Mql(
                    mql_date=_jitter_date(rng, m.mql_date, first, last, DATE_JITTER_DAYS),
                    region=m.region.value,
                    channel=m.channel,
                    campaign=campaigns[(m.channel, m.campaign)],
                )
            )
    return result


def _funnel_rows(deals: Sequence[_Deal], mqls: Sequence[_Mql]) -> list[dict[str, Any]]:
    cells: dict[tuple[date, str, str, str], dict[str, Any]] = {}

    def cell(day: date, region: str, channel: str, campaign: str) -> dict[str, Any]:
        key = (_month(day), region, channel, campaign)
        if key not in cells:
            cells[key] = {
                "period": key[0],
                "region": region,
                "channel": channel,
                "campaign": campaign,
                "leads": 0,
                "mqls": 0,
                "sqls": 0,
                "opportunities": 0,
                "deals_won": 0,
                "revenue": Decimal("0.00"),
            }
        return cells[key]

    for m in mqls:
        cell(m.mql_date, m.region, m.channel, m.campaign)["mqls"] += 1
    for d in deals:
        cell(d.created_at, d.region, d.channel, d.campaign)["opportunities"] += 1
        if d.outcome is DealOutcome.WON and d.closed_at is not None:
            row = cell(d.closed_at, d.region, d.channel, d.campaign)
            row["deals_won"] += 1
            row["revenue"] = _money(row["revenue"] + (d.amount or Decimal(0)))
    return [cells[key] for key in sorted(cells)]


def _competition_rows(deals: Sequence[_Deal]) -> list[dict[str, Any]]:
    competing = sorted(
        (d for d in deals if d.competitors),
        key=lambda d: (d.created_at, d.closed_at or date.max, d.competitors, d.amount or 0),
    )
    return [
        {
            "deal_id": f"demo-{n:04d}",
            "competitor": name,
            "outcome": d.outcome.value,
            "amount": d.amount,
            "closed_at": d.closed_at,
        }
        for n, d in enumerate(competing, start=1)
        for name in d.competitors
    ]


def _campaign_rows(
    campaigns: dict[tuple[str, str], str], mqls: Sequence[_Mql]
) -> list[dict[str, Any]]:
    channels: dict[str, str] = {}
    for (channel, _), name in sorted(campaigns.items()):
        if name:
            channels.setdefault(name, channel)
    dates: dict[str, list[date]] = defaultdict(list)
    for m in mqls:
        dates[m.campaign].append(m.mql_date)
    return [
        {
            "name": name,
            "channel": channels[name],
            "first_mql_at": min(dates[name], default=None),
            "last_mql_at": max(dates[name], default=None),
        }
        for name in sorted(channels)
    ]


def _spend_rows(rng: random.Random, spend: Sequence[SpendRow]) -> list[dict[str, Any]]:
    """Real spend per period x region, times one global scale and a little per-cell noise."""
    totals: dict[tuple[date, str], Decimal] = defaultdict(Decimal)
    for s in spend:
        totals[(s.period, s.region.value)] += s.amount
    real = {s.amount for s in spend} | set(totals.values())
    scale = rng.uniform(*SPEND_SCALE)
    rows: list[dict[str, Any]] = []
    for (period, region), amount in sorted(totals.items()):
        factor = Decimal(str(round(scale * rng.uniform(1 - SPEND_NOISE, 1 + SPEND_NOISE), 6)))
        value = _money(amount * factor)
        if value:  # a zero reveals nothing and stays zero
            value = _avoid(value, real)
        rows.append({"period": period, "region": region, "amount": value})
    return rows


def synthesize(
    deals: Sequence[DealRow], spend: Sequence[SpendRow], mqls: Sequence[MqlRow], *, seed: int
) -> dict[str, pa.Table]:
    """Synthetic tables with the shape of the real data, keyed like `schema.TABLES`."""
    deals = sorted(deals, key=lambda d: d.deal_id)
    spend = sorted(spend, key=lambda s: (s.period, s.region.value, s.amount))
    mqls = sorted(mqls, key=lambda m: (m.mql_date, m.region.value, m.channel, m.campaign))
    rng = random.Random(seed)
    lookup = _channel_lookup(mqls)
    campaigns = _campaign_names(deals, mqls, lookup, seed)

    fake_deals = _synthetic_deals(rng, deals, lookup, campaigns)
    fake_mqls = _synthetic_mqls(rng, mqls, campaigns)
    rows = {
        "funnel_metrics": _funnel_rows(fake_deals, fake_mqls),
        "deals_competition": _competition_rows(fake_deals),
        "campaigns": _campaign_rows(campaigns, fake_mqls),
        "marketing_spend": _spend_rows(rng, spend),
    }
    return {t: pa.Table.from_pylist(rows[t], schema=SCHEMAS[t]) for t in TABLES}


# --- output ---


def write_dataset(tables: dict[str, pa.Table], directory: Path, *, seed: int) -> Manifest:
    """Write one Parquet file per table plus manifest.json to `directory`."""
    if set(tables) != set(TABLES):
        raise ValueError(f"Expected tables {sorted(TABLES)}, got {sorted(tables)}.")
    directory.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for table in TABLES:
        if not tables[table].schema.equals(SCHEMAS[table]):
            raise ValueError(f"Table {table} does not match its schema.")
        path = parquet_path(directory, table)
        pq.write_table(tables[table], path)
        hashes[table] = sha256(path)
    manifest = Manifest(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        seed=seed,
        generator_version=GENERATOR_VERSION,
        row_counts={t: tables[t].num_rows for t in TABLES},
        sha256=hashes,
    )
    manifest.write(directory)
    return manifest


# --- real vs synthetic ---


def _win_rates(pairs: Iterable[tuple[str, str]]) -> dict[str, tuple[int, int]]:
    """(competitor, outcome) pairs -> competitor: (won, closed)."""
    rates: dict[str, tuple[int, int]] = {}
    for name, outcome in pairs:
        if outcome == DealOutcome.OPEN.value:
            continue
        won, closed = rates.get(name, (0, 0))
        rates[name] = (won + (outcome == DealOutcome.WON.value), closed + 1)
    return rates


def compare(
    deals: Sequence[DealRow],
    spend: Sequence[SpendRow],
    mqls: Sequence[MqlRow],
    tables: dict[str, pa.Table],
) -> list[Check]:
    """Real vs synthetic funnel conversion, win rate per competitor and region spend share."""
    checks: list[Check] = []
    funnel = tables["funnel_metrics"].to_pydict()
    opps = sum(funnel["opportunities"])
    won = sum(funnel["deals_won"])
    real_won = sum(d.outcome is DealOutcome.WON for d in deals)
    if deals:
        checks.append(Check("Opportunities -> won", _pct(real_won, len(deals)), _pct(won, opps)))
    if mqls and deals:
        checks.append(
            Check(
                "MQLs -> opportunities",
                _pct(len(deals), len(mqls)),
                _pct(opps, sum(funnel["mqls"])),
            )
        )

    rare = _rare_competitors(deals)
    pool = "Rare competitors (pooled)"

    def group(name: str) -> str:
        return pool if name in rare else name

    real_rates = _win_rates(
        (group(c), d.outcome.value) for d in deals for c in _seed_competitors(d)
    )
    competition = tables["deals_competition"].to_pydict()
    fake_rates = _win_rates(
        (group(c), o)
        for c, o in zip(competition["competitor"], competition["outcome"], strict=True)
    )
    for name in sorted(real_rates):
        r_won, r_closed = real_rates[name]
        f_won, f_closed = fake_rates.get(name, (0, 0))
        one_flip = 100 / r_closed if r_closed else 0.0
        checks.append(
            Check(
                f"Win rate vs {name}",
                _pct(r_won, r_closed),
                _pct(f_won, f_closed),
                tolerance_pp=max(COMPETITOR_TOLERANCE_PP, one_flip),
                must_differ=True,
            )
        )

    real_spend: dict[str, Decimal] = defaultdict(Decimal)
    for s in spend:
        real_spend[s.region.value] += s.amount
    fake_spend: dict[str, Decimal] = defaultdict(Decimal)
    synthetic = tables["marketing_spend"].to_pydict()
    for region, amount in zip(synthetic["region"], synthetic["amount"], strict=True):
        fake_spend[region] += amount
    real_total = sum(real_spend.values(), Decimal(0))
    fake_total = sum(fake_spend.values(), Decimal(0))
    for region in sorted(real_spend):
        checks.append(
            Check(
                f"Spend share {region}",
                _pct(float(real_spend[region]), float(real_total)),
                _pct(float(fake_spend[region]), float(fake_total)),
            )
        )
    return checks
