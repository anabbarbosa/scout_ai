"""Turn HTML into the cleaned text that is hashed and stored (guide Step 3.3).

Only what a visitor reads counts: scripts, menus, footers, forms and cookie banners are
dropped, so a change to a tracking tag or a menu link does not create a new snapshot.
"""

import re

from selectolax.lexbor import LexborHTMLParser, LexborNode

NOISE = (
    "script, style, noscript, template, svg, iframe, nav, footer, form, dialog,"
    " [aria-hidden=true], [id*=cookie], [class*=cookie], [id*=consent], [class*=consent]"
)
# A class like "has-cookie-banner" on these must not drop the whole page.
KEEP = {"html", "body", "main"}

_SPACES = re.compile(r"\s+")


def parse(html: str) -> LexborHTMLParser:
    tree = LexborHTMLParser(html)
    for node in tree.css(NOISE):
        if node.tag not in KEEP:
            node.decompose()
    return tree


# Where the page content lives, in order of preference; sites without <main> often use
# one of the others (the target of their "Skip to main content" link).
CONTENT_ROOTS = ("main", "[role=main]", "#main-content", ".main-content", "#content")


def content_root(tree: LexborHTMLParser) -> LexborNode | None:
    for selector in CONTENT_ROOTS:
        node = tree.css_first(selector)
        if node is not None:
            return node
    return tree.body


def squash(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def clean_text(html: str) -> str:
    """Visible text of the main content, one block per line, without repeated lines."""
    root = content_root(parse(html))
    if root is None:
        return ""
    lines: list[str] = []
    for raw in root.text(separator="\n").splitlines():
        line = squash(raw)
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return "\n".join(lines)
