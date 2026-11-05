"""A fake website for collector tests: serves fixture files through httpx.MockTransport."""

from dataclasses import dataclass, field
from pathlib import Path

import httpx

from scout_ai.collectors.http import PoliteClient

FIXTURES = Path(__file__).parent / "fixtures" / "collectors"
USER_AGENT = "ScoutAI/0.1 (test)"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@dataclass
class FakeSite:
    """URL -> (status, body). Unknown URLs answer 404; robots.txt allows all unless set."""

    pages: dict[str, tuple[int, bytes]] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    errors: set[str] = field(default_factory=set)  # URLs that raise a connection error

    def serve(self, url: str, body: bytes | str, status: int = 200) -> None:
        self.pages[url] = (status, body.encode() if isinstance(body, str) else body)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url in self.errors:
            raise httpx.ConnectError("connection refused", request=request)
        status, body = self.pages.get(url, (404, b"not found"))
        content_type = "text/html; charset=utf-8"
        if url.endswith(".xml"):
            content_type = "application/xml"
        elif url.endswith(".rss"):
            content_type = "application/rss+xml; charset=utf-8"
        return httpx.Response(status, content=body, headers={"Content-Type": content_type})

    def urls(self) -> list[str]:
        return [str(request.url) for request in self.requests]


@dataclass
class FakeClock:
    now: float = 1000.0
    sleeps: list[float] = field(default_factory=list)

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def polite_client(
    site: FakeSite, clock: FakeClock | None = None, delay: float = 5.0
) -> PoliteClient:
    clock = clock or FakeClock()
    client = httpx.Client(transport=httpx.MockTransport(site.handler), follow_redirects=True)
    return PoliteClient(client, user_agent=USER_AGENT, delay=delay, clock=clock, sleep=clock.sleep)
