"""Read-only HubSpot client for deals (guide Step 5).

Only the deal fields the funnel and competition tables need are requested: no deal names,
contacts or companies. Records stay in memory; `scout fetch` turns them into synthetic data.
MQLs come from the Marketing export (marketing_csv.py), so contacts are not read here.
"""

import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx

from scout_ai.db.models import DealOutcome, Region

BASE_URL = "https://api.hubapi.com"
DEAL_SEARCH = "/crm/v3/objects/deals/search"
PAGE_SIZE = 200  # search API maximum
SEARCH_CAP = 10_000  # the search API refuses to page past this
REQUEST_INTERVAL = 0.25  # search API allows 5 requests per second per account

# New-business pipelines; Customer Success (renewal, upsell, contraction) is out of scope.
NEW_BUSINESS_PIPELINES = (
    "47550223",  # Net-New
    "913042183",  # [New] RFP Pipeline
    "678921040",  # RFP Net New
)

COMPETITOR_PROPERTY = "competition__single_select_"
NO_COMPETITOR = "Unknown / None"

PROPERTIES = (
    "pipeline",
    "dealstage",
    "amount",
    "createdate",
    "closedate",
    "hs_is_closed",
    "hs_is_closed_won",
    "sales_region",
    "hs_analytics_source",
    "hs_analytics_source_data_1",
    COMPETITOR_PROPERTY,
)


class HubSpotError(RuntimeError):
    pass


@dataclass(frozen=True)
class DealRow:
    deal_id: str  # real HubSpot ID: memory only, replaced by a synthetic ID on fetch
    pipeline: str
    stage: str
    outcome: DealOutcome
    amount: Decimal | None
    created_at: date
    closed_at: date | None  # only set for closed deals
    region: Region
    channel: str  # Original Traffic Source, e.g. "PAID_SEARCH"
    campaign: str  # Original Traffic Source Drill-Down 1; "" when empty
    competitors: tuple[str, ...]  # HubSpot option labels; empty when unset or "Unknown / None"


def _date(raw: str | None) -> date | None:
    return datetime.fromisoformat(raw).date() if raw else None


def _outcome(props: dict[str, Any]) -> DealOutcome:
    if props.get("hs_is_closed_won") == "true":
        return DealOutcome.WON
    if props.get("hs_is_closed") == "true":
        return DealOutcome.LOST
    return DealOutcome.OPEN


def _to_deal(record: dict[str, Any]) -> DealRow:
    props: dict[str, Any] = record["properties"]
    outcome = _outcome(props)
    created = _date(props.get("createdate"))
    if created is None:
        raise HubSpotError(f"Deal {record['id']} has no createdate.")
    # Some deals hold several options joined by ";" although the property is single-select.
    competitors = tuple(
        name
        for raw in (props.get(COMPETITOR_PROPERTY) or "").split(";")
        if (name := raw.strip()) and name != NO_COMPETITOR
    )
    return DealRow(
        deal_id=record["id"],
        pipeline=props.get("pipeline") or "",
        stage=props.get("dealstage") or "",
        outcome=outcome,
        amount=Decimal(props["amount"]) if props.get("amount") else None,
        created_at=created,
        closed_at=_date(props.get("closedate")) if outcome is not DealOutcome.OPEN else None,
        region=Region.from_label(props.get("sales_region") or ""),
        channel=props.get("hs_analytics_source") or "",
        campaign=props.get("hs_analytics_source_data_1") or "",
        competitors=competitors,
    )


def _search_body(since: date, pipelines: Sequence[str], after: str | None) -> dict[str, Any]:
    since_ms = int(datetime(since.year, since.month, since.day, tzinfo=UTC).timestamp() * 1000)
    body: dict[str, Any] = {
        "filterGroups": [
            {
                "filters": [
                    {"propertyName": "pipeline", "operator": "IN", "values": list(pipelines)},
                    {"propertyName": "createdate", "operator": "GTE", "value": str(since_ms)},
                ]
            }
        ],
        "properties": list(PROPERTIES),
        "sorts": [{"propertyName": "createdate", "direction": "ASCENDING"}],
        "limit": PAGE_SIZE,
    }
    if after is not None:
        body["after"] = after
    return body


def _post(client: httpx.Client, body: dict[str, Any]) -> dict[str, Any]:
    for _ in range(3):
        response = client.post(DEAL_SEARCH, json=body)
        if response.status_code == 429:  # rate limited: wait as told, then retry
            time.sleep(float(response.headers.get("Retry-After", "1")))
            continue
        if response.is_error:
            raise HubSpotError(f"HubSpot search failed ({response.status_code}): {response.text}")
        result: dict[str, Any] = response.json()
        return result
    raise HubSpotError("HubSpot search kept answering 429 (rate limited).")


def _pages(client: httpx.Client, since: date, pipelines: Sequence[str]) -> Iterator[dict[str, Any]]:
    after: str | None = None
    while True:
        page = _post(client, _search_body(since, pipelines, after))
        if page.get("total", 0) > SEARCH_CAP:
            raise HubSpotError(
                f"{page['total']} deals match; the search API stops at {SEARCH_CAP}. "
                "Narrow the date range."
            )
        yield from page.get("results", [])
        after = page.get("paging", {}).get("next", {}).get("after")
        if after is None:
            return
        time.sleep(REQUEST_INTERVAL)


def fetch_deals(
    token: str,
    *,
    since: date,
    pipelines: Sequence[str] = NEW_BUSINESS_PIPELINES,
    client: httpx.Client | None = None,
) -> list[DealRow]:
    """New-business deals created on or after `since`, oldest first."""
    own_client = client is None
    client = client or httpx.Client(base_url=BASE_URL, timeout=30)
    client.headers["Authorization"] = f"Bearer {token}"
    try:
        return [_to_deal(record) for record in _pages(client, since, pipelines)]
    finally:
        if own_client:
            client.close()
