"""Fictional competitor names in what the dashboard shows (scout_ai.aliases)."""

from scout_ai.aliases import ALIASES, mask, mask_text, real_name
from scout_ai.db.seed import COMPETITORS


def test_every_seeded_competitor_has_an_alias() -> None:
    assert {c.name for c in COMPETITORS} == set(ALIASES)


def test_names_are_replaced_whatever_the_case_and_without_doubling_lims() -> None:
    text = "LabWare LIMS vs StarLIMS, then CLINISYS and cloudlims; LabVantage's page"
    assert mask_text(text) == (
        "Kestrel LIMS vs Orbis LIMS, then Meridian Lab Systems and Nimbus LIMS; Halcyon LIMS's page"
    )


def test_owners_and_products_that_would_identify_a_competitor_are_replaced() -> None:
    assert mask_text("Sold by Abbott to Francisco Partners") == (
        "Sold by a diagnostics group to a private equity firm"
    )


def test_links_to_competitor_sites_are_dropped_and_others_kept() -> None:
    text = (
        "See [the food page](https://www.labware.com/food) and https://careers.clinisys.com/jobs.rss"
        " or [our page](https://get.confience.io/x)"
    )
    assert mask_text(text) == "See the food page and  or [our page](https://get.confience.io/x)"


def test_mask_walks_json_and_nulls_competitor_urls() -> None:
    value = {
        "competitor": "LabWare",
        "url": "https://cloudlims.com/news/",
        "evidence": [{"url": "https://hubspot.example/deal", "label": "Clinisys deal"}],
        "count": 3,
    }
    assert mask(value) == {
        "competitor": "Kestrel LIMS",
        "url": None,
        "evidence": [{"url": "https://hubspot.example/deal", "label": "Meridian Lab Systems deal"}],
        "count": 3,
    }


def test_real_name_maps_an_alias_back() -> None:
    assert real_name("Orbis LIMS") == "STARLIMS"
    assert real_name("STARLIMS") == "STARLIMS"
