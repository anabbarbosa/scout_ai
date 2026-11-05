import httpx
import pytest

from scout_ai.collectors.base import BlockedError, CollectorError
from scout_ai.collectors.http import MAX_BYTES, PoliteClient
from tests.collector_site import USER_AGENT, FakeClock, FakeSite, polite_client

ROOT = "https://acme.test"


def test_identifies_the_bot_and_checks_robots_first() -> None:
    site = FakeSite()
    site.serve(f"{ROOT}/robots.txt", "User-agent: *\nDisallow:\n")
    site.serve(f"{ROOT}/", "<p>hi</p>")
    page = polite_client(site).get(f"{ROOT}/")
    assert page.text == "<p>hi</p>"
    assert site.urls() == [f"{ROOT}/robots.txt", f"{ROOT}/"]
    assert all(request.headers["User-Agent"] == USER_AGENT for request in site.requests)


def test_robots_disallow_blocks_without_fetching_the_page() -> None:
    site = FakeSite()
    site.serve(f"{ROOT}/robots.txt", "User-agent: ScoutAI\nDisallow: /blog\n")
    with pytest.raises(BlockedError, match=r"robots\.txt"):
        polite_client(site).get(f"{ROOT}/blog")
    assert site.urls() == [f"{ROOT}/robots.txt"]


@pytest.mark.parametrize(("status", "blocked"), [(401, True), (403, True), (404, False)])
def test_robots_status(status: int, blocked: bool) -> None:
    site = FakeSite()
    site.serve(f"{ROOT}/robots.txt", "", status=status)
    site.serve(f"{ROOT}/", "ok")
    client = polite_client(site)
    if blocked:
        with pytest.raises(BlockedError):
            client.get(f"{ROOT}/")
    else:
        assert client.get(f"{ROOT}/").text == "ok"


def test_unreachable_robots_is_a_failure_and_not_retried_in_the_run() -> None:
    site = FakeSite()
    site.serve(f"{ROOT}/robots.txt", "", status=503)
    client = polite_client(site)
    for path in ("/a", "/b"):
        with pytest.raises(CollectorError, match=r"robots\.txt unreachable") as info:
            client.get(f"{ROOT}{path}")
        assert not isinstance(info.value, BlockedError)
    assert site.urls() == [f"{ROOT}/robots.txt"]


@pytest.mark.parametrize(("status", "error"), [(403, BlockedError), (500, CollectorError)])
def test_http_errors(status: int, error: type[CollectorError]) -> None:
    site = FakeSite()
    site.serve(f"{ROOT}/page", "nope", status=status)
    with pytest.raises(error, match=f"HTTP {status}"):
        polite_client(site).get(f"{ROOT}/page")


def test_network_errors_become_collector_errors() -> None:
    site = FakeSite(errors={f"{ROOT}/page"})
    with pytest.raises(CollectorError, match="ConnectError"):
        polite_client(site).get(f"{ROOT}/page")


def test_rejects_huge_responses() -> None:
    site = FakeSite()
    site.serve(f"{ROOT}/page", b"x" * (MAX_BYTES + 1))
    with pytest.raises(CollectorError, match="larger than"):
        polite_client(site).get(f"{ROOT}/page")


def test_redirect_target_is_checked_against_robots() -> None:
    site = FakeSite()
    site.serve(f"{ROOT}/robots.txt", "User-agent: *\nDisallow: /members/\n")
    site.pages[f"{ROOT}/news"] = (301, b"")

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == f"{ROOT}/news":
            site.requests.append(request)
            return httpx.Response(301, headers={"Location": f"{ROOT}/members/news"})
        return site.handler(request)

    clock = FakeClock()
    client = PoliteClient(
        httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True),
        user_agent=USER_AGENT,
        delay=0,
        clock=clock,
        sleep=clock.sleep,
    )
    with pytest.raises(BlockedError):
        client.get(f"{ROOT}/news")


def test_waits_between_requests_to_the_same_host_only() -> None:
    site = FakeSite()
    for url in (f"{ROOT}/a", f"{ROOT}/b", "https://other.test/a"):
        site.serve(url, "ok")
    clock = FakeClock()
    client = polite_client(site, clock, delay=5.0)
    client.get(f"{ROOT}/a")  # robots.txt then /a: one wait between them
    client.get("https://other.test/a")  # another host: its own robots.txt, one wait
    client.get(f"{ROOT}/b")  # last request to acme was 5 s ago: no wait
    assert clock.sleeps == [5.0, 5.0]


def test_crawl_delay_raises_the_wait() -> None:
    site = FakeSite()
    site.serve(f"{ROOT}/robots.txt", "User-agent: *\nCrawl-delay: 12\n")
    site.serve(f"{ROOT}/a", "ok")
    clock = FakeClock()
    polite_client(site, clock, delay=5.0).get(f"{ROOT}/a")
    assert clock.sleeps == [12.0]


def test_responses_are_cached_for_the_run() -> None:
    site = FakeSite()
    site.serve(f"{ROOT}/a", "ok")
    client = polite_client(site)
    client.get(f"{ROOT}/a")
    client.get(f"{ROOT}/a")
    assert site.urls().count(f"{ROOT}/a") == 1
