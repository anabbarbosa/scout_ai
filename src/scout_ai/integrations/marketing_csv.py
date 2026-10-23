"""Readers for Marketing's cost exports in data/raw/ (guide Step 5).

Two CSVs, exported from Excel on Windows (cp1252):

- "Monthly MQL Cost Summary": a formatted report, one block per month ("January 2026", a
  header row, one row per region, a "Total" row). Only the spend per region is read; the
  other columns (MQLs, pipeline, closed won) come from HubSpot.
- "MQL Count": one row per MQL and company. Only date, region, channel and campaign are
  read; names and contact IDs are used to drop duplicates and never leave this module.
"""

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from scout_ai.db.models import Region

ENCODING = "cp1252"
SPEND_PATTERN = "*Monthly MQL Cost Summary*.csv"
MQL_PATTERN = "*MQL Count*.csv"

NO_VALUE = "(No value)"


class MarketingCSVError(ValueError):
    pass


@dataclass(frozen=True)
class SpendRow:
    period: date  # first day of the month
    region: Region
    amount: Decimal


@dataclass(frozen=True)
class MqlRow:
    mql_date: date
    region: Region
    channel: str  # HubSpot "Original Source", e.g. "Paid Search"
    campaign: str  # "Original Source Drill-Down 1"; "" when HubSpot has no value


def find_export(raw_dir: Path, pattern: str) -> Path:
    matches = sorted(raw_dir.glob(pattern))
    if len(matches) != 1:
        found = ", ".join(p.name for p in matches) or "nothing"
        raise MarketingCSVError(f"Expected one {pattern!r} in {raw_dir}, found {found}.")
    return matches[0]


def _rows(path: Path) -> Iterator[list[str]]:
    with path.open(encoding=ENCODING, newline="") as f:
        yield from csv.reader(f)


def _money(raw: str) -> Decimal:
    return Decimal(raw.replace("$", "").replace(",", "").strip() or "0")


def _month_title(cell: str) -> date | None:
    try:
        return datetime.strptime(cell.strip(), "%B %Y").date()
    except ValueError:
        return None


def read_spend(path: Path) -> list[SpendRow]:
    """Spend per month and region; "Total" rows are skipped, since totals are sums."""
    rows: list[SpendRow] = []
    period: date | None = None
    spend_col: int | None = None
    for cells in _rows(path):
        label = cells[1].strip() if len(cells) > 1 else ""
        if (title := _month_title(label)) is not None:
            period, spend_col = title, None
        elif label == "Region":
            spend_col = cells.index("Spend")
        elif period is not None and spend_col is not None and label:
            if label == "Total":
                period = None  # block finished; wait for the next month title
            else:
                rows.append(SpendRow(period, Region.from_label(label), _money(cells[spend_col])))
    if not rows:
        raise MarketingCSVError(f"No monthly spend blocks found in {path.name}.")
    return rows


def read_mqls(path: Path) -> list[MqlRow]:
    """One row per contact and MQL date (the export repeats a contact for each company)."""
    rows = _rows(path)
    header = next(rows)
    try:
        date_col = header.index("Most Recent Date: MQL")
        region_col = header.index("Sales Region")
        contact_col = header.index("Contact ID")
        channel_col = header.index("Original Source")
        campaign_col = header.index("Original Source Drill-Down 1")
    except ValueError as e:
        raise MarketingCSVError(f"Unexpected columns in {path.name}: {e}") from e

    seen: set[tuple[str, str]] = set()
    mqls: list[MqlRow] = []
    for cells in rows:
        if not cells or not cells[date_col].strip():
            continue
        key = (cells[contact_col], cells[date_col])
        if key in seen:
            continue
        seen.add(key)
        campaign = cells[campaign_col].strip()
        mqls.append(
            MqlRow(
                mql_date=date.fromisoformat(cells[date_col].strip()),
                region=Region.from_label(cells[region_col]),
                channel=cells[channel_col].strip(),
                campaign="" if campaign == NO_VALUE else campaign,
            )
        )
    return mqls
