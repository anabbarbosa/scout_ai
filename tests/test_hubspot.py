import json
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest

from scout_ai.db.models import DealOutcome, Region
from scout_ai.integrations import hubspot
from scout_ai.integrations.hubspot import HubSpotError, fetch_deals


def _deal(deal_id: str, **props: str) -> dict[str, Any]:
    base = {"pipeline": "47550223", "dealstage": "98048618", "createdate": "2026-01-05T10:00:00Z"}
    return {"id": deal_id, "properties": base | props}


def _client(pages: list[dict[str, Any]], requests: list[httpx.Request]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=pages[len(requests) - 1])

    return httpx.Client(base_url=hubspot.BASE_URL, transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hubspot.time, "sleep", lambda _: None)


def test_fetch_deals_pages_and_maps_fields() -> None:
    pages = [
        {
            "total": 3,
            "results": [
                _deal(
                    "1",
                    amount="1500.50",
                    hs_is_closed="true",
                    hs_is_closed_won="true",
                    closedate="2026-03-01T00:00:00Z",
                    sales_region="BRAZIL",
                    hs_analytics_source="PAID_SEARCH",
                    hs_analytics_source_data_1="search_competitor",
                    competition__single_select_="LabWare; UltraLIMS",
                ),
                _deal("2", hs_is_closed="true", hs_is_closed_won="false", sales_region="NA"),
            ],
            "paging": {"next": {"after": "2"}},
        },
        {
            "total": 3,
            "results": [
                _deal(
                    "3",
                    closedate="2026-12-31T00:00:00Z",  # expected close of an open deal: dropped
                    competition__single_select_="Unknown / None",
                )
            ],
        },
    ]
    requests: list[httpx.Request] = []
    deals = fetch_deals("token", since=date(2026, 1, 1), client=_client(pages, requests))

    won, lost, open_ = deals
    assert (won.outcome, won.amount, won.closed_at) == (
        DealOutcome.WON,
        Decimal("1500.50"),
        date(2026, 3, 1),
    )
    assert (won.region, won.channel, won.campaign, won.competitors) == (
        Region.BRAZIL,
        "PAID_SEARCH",
        "search_competitor",
        ("LabWare", "UltraLIMS"),
    )
    assert (lost.outcome, lost.region, lost.amount) == (
        DealOutcome.LOST,
        Region.NORTH_AMERICA,
        None,
    )
    assert (open_.outcome, open_.closed_at, open_.competitors) == (DealOutcome.OPEN, None, ())

    assert requests[0].headers["Authorization"] == "Bearer token"
    first, second = (json.loads(r.content) for r in requests)
    assert "after" not in first and second["after"] == "2"
    pipeline_filter, date_filter = first["filterGroups"][0]["filters"]
    assert pipeline_filter["values"] == list(hubspot.NEW_BUSINESS_PIPELINES)
    assert date_filter == {
        "propertyName": "createdate",
        "operator": "GTE",
        "value": "1767225600000",
    }


def test_fetch_deals_retries_after_rate_limit() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json={"total": 1, "results": [_deal("1")]})

    client = httpx.Client(base_url=hubspot.BASE_URL, transport=httpx.MockTransport(handler))
    assert len(fetch_deals("t", since=date(2026, 1, 1), client=client)) == 1
    assert calls == 2


def test_fetch_deals_raises_on_errors_and_search_cap() -> None:
    error = httpx.Client(
        base_url=hubspot.BASE_URL,
        transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"message": "bad"})),
    )
    with pytest.raises(HubSpotError, match="401"):
        fetch_deals("t", since=date(2026, 1, 1), client=error)

    capped = _client([{"total": 10_001, "results": []}], [])
    with pytest.raises(HubSpotError, match="10000"):
        fetch_deals("t", since=date(2026, 1, 1), client=capped)
