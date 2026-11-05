"""Polite HTTP access shared by the collectors (guide Step 3.2).

Every request identifies the bot in its User-Agent, is checked against the site's
robots.txt and waits between requests to the same host. Responses are cached for the
rest of the run, so a URL used by two sources is fetched once.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from scout_ai.collectors.base import BlockedError, CollectorError
from scout_ai.collectors.robots import RobotsRules

MAX_BYTES = 5_000_000
# Some sites ask for long Crawl-delays; past this we still wait, but only this long.
MAX_CRAWL_DELAY = 60.0


@dataclass(frozen=True)
class Page:
    url: str  # after redirects
    content: bytes
    encoding: str
    content_type: str = ""  # media type only, e.g. "text/html"

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding, errors="replace")


class PoliteClient:
    def __init__(
        self,
        client: httpx.Client,
        *,
        user_agent: str,
        delay: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._user_agent = user_agent
        # robots.txt groups are matched on the product token: "ScoutAI/0.1 (...)" -> "scoutai"
        self._token = user_agent.split("/", 1)[0].split()[0].lower()
        self._delay = delay
        self._clock = clock
        self._sleep = sleep
        self._robots: dict[str, RobotsRules | CollectorError] = {}
        self._last_request: dict[str, float] = {}
        self._cache: dict[str, Page] = {}

    def get(self, url: str) -> Page:
        if url in self._cache:
            return self._cache[url]
        self._check_robots(url)
        response = self._request(url)
        final_url = str(response.url)
        if final_url != url:
            self._check_robots(final_url)  # redirected to a path or host robots.txt may forbid
        if response.status_code in (401, 403):
            raise BlockedError(f"HTTP {response.status_code}")
        if response.status_code >= 400:
            raise CollectorError(f"HTTP {response.status_code}")
        if len(response.content) > MAX_BYTES:
            raise CollectorError(f"response larger than {MAX_BYTES} bytes")
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        page = Page(final_url, response.content, response.encoding or "utf-8", content_type)
        self._cache[url] = page
        return page

    def _check_robots(self, url: str) -> None:
        if not self._robots_for(url).allowed(url):
            raise BlockedError("disallowed by robots.txt")

    def _robots_for(self, url: str) -> RobotsRules:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = self._load_robots(origin)
        rules = self._robots[origin]
        if isinstance(rules, CollectorError):
            raise rules
        return rules

    def _load_robots(self, origin: str) -> RobotsRules | CollectorError:
        try:
            response = self._request(f"{origin}/robots.txt")
        except CollectorError as error:
            return CollectorError(f"robots.txt unreachable ({error})")
        status = response.status_code
        if status in (401, 403):
            return RobotsRules.disallow_all()  # the site refuses bots outright
        if 400 <= status < 500:
            return RobotsRules.allow_all()  # no robots.txt: RFC 9309 allows everything
        if status >= 500:
            # RFC 9309: assume everything is disallowed while robots.txt is unavailable.
            return CollectorError(f"robots.txt unreachable (HTTP {status})")
        return RobotsRules.parse(response.text, self._token)

    def _request(self, url: str) -> httpx.Response:
        host = urlsplit(url).netloc
        delay = self._delay
        rules = self._robots.get(f"{urlsplit(url).scheme}://{host}")
        if isinstance(rules, RobotsRules) and rules.crawl_delay is not None:
            delay = max(delay, min(rules.crawl_delay, MAX_CRAWL_DELAY))
        last = self._last_request.get(host)
        if last is not None:
            wait = last + delay - self._clock()
            if wait > 0:
                self._sleep(wait)
        try:
            return self._client.get(url, headers={"User-Agent": self._user_agent})
        except httpx.HTTPError as error:
            raise CollectorError(f"{type(error).__name__}: {error}") from error
        finally:
            self._last_request[host] = self._clock()
