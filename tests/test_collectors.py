"""Page and listing collectors against saved HTML fixtures (guide Step 3 "Done when")."""

import pytest

from scout_ai.collectors import build_collectors
from scout_ai.collectors.base import CollectorError, content_hash
from scout_ai.collectors.listing import ListingCollector, feed_items, find_feed, html_items
from scout_ai.collectors.page import PageCollector
from scout_ai.collectors.text import clean_text
from scout_ai.db.models import Source, SourceType
from tests.collector_site import FakeSite, fixture, polite_client

ROOT = "https://acme.test"


def _source(url: str, source_type: SourceType = SourceType.HOMEPAGE) -> Source:
    return Source(id=7, competitor_id=1, type=source_type, url=url)


def test_clean_text_keeps_only_what_a_visitor_reads() -> None:
    text = clean_text(fixture("homepage.html").decode())
    assert text.splitlines() == [
        "Industries",
        "Pharma",
        "Food & beverage",
        "Environmental",
        "Why Acme",
        "Configurable without code.",
    ]


def test_clean_text_without_main_uses_the_body() -> None:
    html = "<body><nav>Menu</nav><header><h1>Hello   world</h1></header><p>Text</p></body>"
    assert clean_text(html) == "Hello world\nText"


def test_clean_text_ignores_markup_only_changes() -> None:
    html = fixture("homepage.html").decode()
    changed = html.replace("a1b2c3", "zzz").replace("Privacy policy", "Terms")
    assert clean_text(changed) == clean_text(html)


def test_page_collector() -> None:
    site = FakeSite()
    site.serve(f"{ROOT}/", fixture("homepage.html"))
    snapshot = PageCollector(polite_client(site)).fetch(_source(f"{ROOT}/"))
    assert snapshot.source_id == 7
    assert snapshot.raw_text.startswith("Industries\nPharma")
    assert snapshot.content_hash == content_hash(snapshot.raw_text)


def test_page_without_text_fails() -> None:
    site = FakeSite()
    site.serve(f"{ROOT}/", "<html><body><script>render()</script><div id=app></div></body></html>")
    with pytest.raises(CollectorError, match="browser"):
        PageCollector(polite_client(site)).fetch(_source(f"{ROOT}/"))


def test_find_feed_only_accepts_the_pages_own_feed() -> None:
    html = fixture("blog_with_feed.html").decode()
    assert find_feed(html, f"{ROOT}/blog") == f"{ROOT}/blog/rss.xml"
    assert find_feed(html, f"{ROOT}/news") is None  # /blog/rss.xml is not under /news/


def test_rss_items() -> None:
    items = feed_items(fixture("blog_rss.xml"), f"{ROOT}/blog/rss.xml")
    assert [item.line() for item in items] == [
        f"Mon, 02 Nov 2026 10:00:00 GMT | ISO 17025 and your LIMS | {ROOT}/blog/iso-17025",
        f"Tue, 20 Oct 2026 09:00:00 GMT | Building the connected lab | {ROOT}/blog/connected-lab",
    ]


def test_atom_items() -> None:
    items = feed_items(fixture("news_atom.xml"), f"{ROOT}/news/atom.xml")
    assert [(item.title, item.url, item.published) for item in items] == [
        ("Acme opens an office in São Paulo", f"{ROOT}/news/sao-paulo", "2026-11-01T12:00:00Z"),
        ("Acme releases version 5", f"{ROOT}/news/v5", "2026-10-15T08:00:00Z"),
    ]


def test_html_items_from_articles() -> None:
    items = html_items(fixture("press_articles.html").decode(), f"{ROOT}/news/")
    assert [(item.title, item.url) for item in items] == [
        ("Acme partners with SampleCo", f"{ROOT}/news/partnership"),  # duplicate dropped
        ("Acme adds a CAPA module", f"{ROOT}/news/capa"),
        ("Acme wins a lab informatics award", f"{ROOT}/news/award"),
    ]


def test_html_items_from_heading_links() -> None:
    items = html_items(fixture("news_headings.html").decode(), f"{ROOT}/news")
    assert [(item.title, item.url) for item in items] == [
        ("Acme reports Q3 results", f"{ROOT}/news/q3-results"),
        ("Acme names a new CEO", f"{ROOT}/news/new-ceo"),
    ]


def test_hub_page_has_no_items() -> None:
    assert html_items(fixture("events_hub.html").decode(), f"{ROOT}/events") == []


def test_listing_prefers_the_feed() -> None:
    site = FakeSite()
    site.serve(f"{ROOT}/blog", fixture("blog_with_feed.html"))
    site.serve(f"{ROOT}/blog/rss.xml", fixture("blog_rss.xml"))
    snapshot = ListingCollector(polite_client(site)).fetch(_source(f"{ROOT}/blog", SourceType.BLOG))
    assert "ISO 17025 and your LIMS" in snapshot.raw_text
    assert "from the HTML" not in snapshot.raw_text


@pytest.mark.parametrize("feed", [b"<rss><channel><item>", None])
def test_listing_falls_back_to_html_when_the_feed_fails(feed: bytes | None) -> None:
    site = FakeSite()
    site.serve(f"{ROOT}/blog", fixture("blog_with_feed.html"))
    if feed is not None:
        site.serve(f"{ROOT}/blog/rss.xml", feed)  # broken XML; None means a 404
    snapshot = ListingCollector(polite_client(site)).fetch(_source(f"{ROOT}/blog", SourceType.BLOG))
    assert snapshot.raw_text == (
        f"First post from the HTML | {ROOT}/blog/first-post\n"
        f"Second post from the HTML | {ROOT}/blog/second-post"
    )


def test_listing_falls_back_to_page_text_for_hubs() -> None:
    site = FakeSite()
    site.serve(f"{ROOT}/events", fixture("events_hub.html"))
    snapshot = ListingCollector(polite_client(site)).fetch(
        _source(f"{ROOT}/events", SourceType.EVENTS)
    )
    assert snapshot.raw_text.startswith("Acme Events\nJoin us")


def test_every_seeded_source_type_has_a_collector() -> None:
    from scout_ai.db.seed import COMPETITORS

    collectors = build_collectors(polite_client(FakeSite()))
    seeded = {source_type for c in COMPETITORS for source_type, _, _ in c.sources}
    assert seeded <= collectors.keys()
    assert SourceType.REVIEWS not in collectors  # G2/Capterra terms forbid scraping


def test_job_board_feed_as_the_source_url() -> None:
    site = FakeSite()
    site.serve("https://jobs.acme.test/jobs.rss", fixture("jobs_teamtailor.rss"))
    source = _source("https://jobs.acme.test/jobs.rss", SourceType.JOBS)
    snapshot = ListingCollector(polite_client(site)).fetch(source)
    assert snapshot.raw_text.splitlines() == [
        "Thu, 05 Nov 2026 12:20:41 +0000 | Implementation Consultant"
        " | Brazil, Colombia, Professional Services"
        " | https://jobs.acme.test/jobs/101-implementation-consultant",
        "Mon, 02 Nov 2026 09:00:00 +0000 | LIMS Developer | Software Development"
        " | https://jobs.acme.test/jobs/102-lims-developer",
    ]


def test_empty_job_board_feed_is_stored() -> None:
    site = FakeSite()
    site.serve("https://jobs.acme.test/jobs.rss", "<rss><channel><title>x</title></channel></rss>")
    source = _source("https://jobs.acme.test/jobs.rss", SourceType.JOBS)
    assert ListingCollector(polite_client(site)).fetch(source).raw_text == "(no items)"


def test_broken_feed_source_fails() -> None:
    site = FakeSite()
    site.serve("https://jobs.acme.test/jobs.rss", "<rss><channel>")
    source = _source("https://jobs.acme.test/jobs.rss", SourceType.JOBS)
    with pytest.raises(CollectorError, match="invalid feed"):
        ListingCollector(polite_client(site)).fetch(source)


@pytest.mark.parametrize(
    "wrapper",
    ['<div class="main-content site">', '<div id="main-content">', '<div role="main">'],
)
def test_clean_text_finds_content_without_main(wrapper: str) -> None:
    html = (
        '<body><a class="screen-reader-text" href="#c">Skip to main content</a>'
        "<header><div>Solutions</div><div>Search</div></header>"
        f"{wrapper}<h1>Environmental LIMS</h1><p>Water and soil labs.</p></div></body>"
    )
    assert clean_text(html) == "Environmental LIMS\nWater and soil labs."
