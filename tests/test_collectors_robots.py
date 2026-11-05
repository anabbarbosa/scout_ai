import pytest

from scout_ai.collectors.robots import RobotsRules

# Shaped like the competitor sites' files: indented lines, repeated `*` groups, wildcards.
ROBOTS = """
User-agent: *
Disallow:
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php
            Disallow: /sample-*

User-agent: *
User-agent: SemrushBot
Disallow: /*/feed/   # comments are ignored
Disallow: /*.pdf$
Crawl-delay: 2

User-agent: ScoutAI
Disallow: /private/
Crawl-delay: 10
"""


@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("/", True),
        ("/blog/", True),
        ("/wp-admin/options.php", False),
        ("/wp-admin/admin-ajax.php", True),  # longer Allow beats shorter Disallow
        ("/sample-request", False),
        ("/blog/feed/", False),  # `*` matches any characters
        ("/feed/", True),  # `/*/feed/` needs a segment before /feed/
        ("/brochure.pdf", False),
        ("/brochure.pdf?v=2", True),  # `$` anchors the end
        ("/private/x", True),  # the ScoutAI group is not used for other agents
        ("/robots.txt", True),
    ],
)
def test_star_group_rules(path: str, allowed: bool) -> None:
    rules = RobotsRules.parse(ROBOTS, "otherbot")
    assert rules.allowed(f"https://acme.test{path}") is allowed


def test_named_group_replaces_the_star_groups() -> None:
    rules = RobotsRules.parse(ROBOTS, "scoutai")
    assert not rules.allowed("https://acme.test/private/x")
    assert rules.allowed("https://acme.test/wp-admin/options.php")
    assert rules.crawl_delay == 10


def test_star_groups_are_combined() -> None:
    assert RobotsRules.parse(ROBOTS, "otherbot").crawl_delay == 2


def test_allow_wins_a_tie() -> None:
    rules = RobotsRules.parse("User-agent: *\nDisallow: /page\nAllow: /page\n", "scoutai")
    assert rules.allowed("https://acme.test/page")


def test_query_string_is_matched() -> None:
    rules = RobotsRules.parse("User-agent: *\nDisallow: /*?*preview=\n", "scoutai")
    assert not rules.allowed("https://acme.test/blog?preview=1")
    assert rules.allowed("https://acme.test/blog?page=2")


def test_empty_file_and_presets() -> None:
    assert RobotsRules.parse("", "scoutai").allowed("https://acme.test/anything")
    assert RobotsRules.allow_all().allowed("https://acme.test/anything")
    assert not RobotsRules.disallow_all().allowed("https://acme.test/anything")
