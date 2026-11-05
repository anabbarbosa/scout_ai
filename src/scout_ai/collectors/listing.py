"""Listings (blog, press, events, jobs): store the list of items, one per line.

Storing titles and links instead of the whole page means a new post shows up as a new
line, and teasers or "read more" widgets changing around it do not create a snapshot.

In order of preference (guide Step 3.2):
1. a feed: the source URL itself (e.g. a job board's jobs.rss), or the page's own
   RSS/Atom feed when the page links to one under its own path (a site-wide feed would
   mix blog posts and press releases);
2. items found in the HTML: <article> elements, or headings that link to a page;
3. the page's cleaned text, for hub pages that link to sections instead of items.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from urllib.parse import urldefrag, urljoin, urlsplit

from selectolax.lexbor import LexborNode

from scout_ai.collectors.base import CollectorError, make_snapshot
from scout_ai.collectors.http import Page, PoliteClient
from scout_ai.collectors.text import clean_text, content_root, parse, squash
from scout_ai.db.models import Snapshot, Source

FEED_TYPES = ("application/rss+xml", "application/atom+xml")
XML_TYPES = (*FEED_TYPES, "application/xml", "text/xml")
# Feed fields worth keeping besides the title, by local name: job boards such as
# Teamtailor add the department and the countries of each opening.
DETAIL_FIELDS = ("department", "country")
ATOM = "{http://www.w3.org/2005/Atom}"
# Fewer than this many items and the page is treated as a hub, not a listing.
MIN_ITEMS = 2


@dataclass(frozen=True)
class Item:
    title: str
    url: str
    published: str = ""
    details: str = ""

    def line(self) -> str:
        parts = [self.published, self.title, self.details, self.url]
        return " | ".join(part for part in parts if part)


class ListingCollector:
    def __init__(self, http: PoliteClient) -> None:
        self.http = http

    def fetch(self, source: Source) -> Snapshot:
        page = self.http.get(source.url)
        if page.content_type in XML_TYPES:
            try:
                items = feed_items(page.content, page.url)
            except ET.ParseError as error:
                raise CollectorError(f"invalid feed: {error}") from error
            # An empty feed is a real state (no openings), so it is stored too.
            text = "\n".join(item.line() for item in items) or "(no items)"
            return make_snapshot(source, text)
        items = self._feed_items(page) or html_items(page.text, page.url)
        if items:
            return make_snapshot(source, "\n".join(item.line() for item in items))
        return make_snapshot(source, clean_text(page.text))

    def _feed_items(self, page: Page) -> list[Item]:
        feed_url = find_feed(page.text, page.url)
        if feed_url is None:
            return []
        try:
            feed = self.http.get(feed_url)
            return feed_items(feed.content, feed.url)
        except CollectorError, ET.ParseError:
            return []  # fall back to the HTML listing


def find_feed(html: str, page_url: str) -> str | None:
    """The page's own feed: same host, under the page's path."""
    page = urlsplit(page_url)
    prefix = page.path.rstrip("/") + "/"
    for link in parse(html).css("link[rel=alternate][href]"):
        if link.attributes.get("type") not in FEED_TYPES:
            continue
        url = urljoin(page_url, link.attributes.get("href") or "")
        parts = urlsplit(url)
        if parts.netloc == page.netloc and parts.path.startswith(prefix):
            return url
    return None


def feed_items(content: bytes, base_url: str) -> list[Item]:
    root = ET.fromstring(content)
    items: list[Item | None] = []
    if root.tag == f"{ATOM}feed":
        for entry in root.iter(f"{ATOM}entry"):
            link = next(
                (
                    node.get("href", "")
                    for node in entry.iter(f"{ATOM}link")
                    if node.get("rel", "alternate") == "alternate"
                ),
                "",
            )
            published = entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated")
            items.append(_item(entry.findtext(f"{ATOM}title"), link, base_url, published))
    else:
        for node in root.iter("item"):
            title, href = node.findtext("title"), node.findtext("link")
            item = _item(title, href, base_url, node.findtext("pubDate"))
            if item is not None:
                item = replace(item, details=_details(node))
            items.append(item)
    return _dedupe([item for item in items if item is not None])


def _details(node: ET.Element) -> str:
    """Department and countries of a job opening, without repeats, in feed order."""
    values: list[str] = []
    for child in node.iter():
        local_name = child.tag.rsplit("}", 1)[-1]
        value = squash(child.text or "")
        if local_name in DETAIL_FIELDS and value and value not in values:
            values.append(value)
    return ", ".join(values)


def html_items(html: str, base_url: str) -> list[Item]:
    root = content_root(parse(html))
    if root is None:
        return []
    articles = root.css("article")
    if len(articles) >= MIN_ITEMS:
        candidates = [_article_item(article, base_url) for article in articles]
    else:
        candidates = [_heading_item(heading, base_url) for heading in root.css("h2, h3, h4")]
    items = _dedupe([item for item in candidates if item is not None])
    return items if len(items) >= MIN_ITEMS else []


def _article_item(article: LexborNode, base_url: str) -> Item | None:
    heading = article.css_first("h1, h2, h3, h4, h5")
    if heading is not None:
        link = _heading_link(heading) or article.css_first("a[href]")
        title = heading.text()
    else:
        # No heading: the title is the first link with text (the first is often the image).
        link = next((a for a in article.css("a[href]") if squash(a.text())), None)
        title = link.text() if link is not None else ""
    if link is None:
        return None
    return _item(title, link.attributes.get("href"), base_url)


def _heading_item(heading: LexborNode, base_url: str) -> Item | None:
    link = _heading_link(heading)
    if link is None:
        return None
    return _item(heading.text(), link.attributes.get("href"), base_url)


def _heading_link(heading: LexborNode) -> LexborNode | None:
    """A link inside the heading, or one wrapping it (<a><h3>Title</h3></a>)."""
    inner = heading.css_first("a[href]")
    if inner is not None:
        return inner
    node = heading.parent
    for _ in range(3):
        if node is None:
            return None
        if node.tag == "a" and node.attributes.get("href"):
            return node
        node = node.parent
    return None


def _item(
    title: str | None, href: str | None, base_url: str, published: str | None = None
) -> Item | None:
    title = squash(title or "")
    url = urldefrag(urljoin(base_url, squash(href or ""))).url
    if not title or urlsplit(url).scheme not in ("http", "https"):
        return None
    return Item(title, url, squash(published or ""))


def _dedupe(items: list[Item]) -> list[Item]:
    """Carousels and "featured" blocks repeat items; keep the first occurrence of each URL."""
    seen: set[str] = set()
    unique = []
    for item in items:
        if item.url not in seen:
            seen.add(item.url)
            unique.append(item)
    return unique
