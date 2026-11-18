"""Fictional competitor names for everything the dashboard shows.

The database, the collectors and the HubSpot import keep the real names (they match deals
and crawl the real sites). The dashboard's internal numbers are synthetic, so showing them
next to real companies would attribute made-up win rates to them: the API answers with
these aliases instead, and drops links to the competitors' own sites, so the pages do not
say which company is which.
"""

import re
from typing import Any

ALIASES = {
    "LabWare": "Kestrel LIMS",
    "STARLIMS": "Orbis LIMS",
    "Clinisys": "Meridian Lab Systems",
    "LabVantage": "Halcyon LIMS",
    "CloudLIMS": "Nimbus LIMS",
}
REAL_NAMES = {alias: real for real, alias in ALIASES.items()}

# Owners and products that would name the company behind an alias.
_TERMS = {
    "HORIZON LIMS": "its environmental LIMS",
    "Sunquest": "a clinical LIS",
    "Orchard Software": "a clinical software vendor",
    "Roper Technologies": "its parent group",
    "Francisco Partners": "a private equity firm",
    "Turn/River Capital": "a private equity firm",
    "Abbott": "a diagnostics group",
}

# A real name, with a trailing "LIMS" that the alias already carries.
_NAME = re.compile(
    r"\b(" + "|".join(re.escape(name) for name in ALIASES) + r")(?:\s+LIMS\b)?",
    re.IGNORECASE,
)
_TERM = re.compile("|".join(re.escape(term) for term in _TERMS), re.IGNORECASE)
_CASEFOLDED = {name.casefold(): alias for name, alias in ALIASES.items()}
_TERMS_CASEFOLDED = {term.casefold(): text for term, text in _TERMS.items()}

_URL = r"https?://[^\s)\]\"'<>]+"
_COMPETITOR_HOST = re.compile(
    r"^https?://([^/]*\.)?(" + "|".join(name.casefold() for name in ALIASES) + r")\.",
    re.IGNORECASE,
)
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\((" + _URL + r")\)")
_BARE_URL = re.compile(_URL)
_URL_KEYS = {"url", "website"}


def is_competitor_url(url: str) -> bool:
    return bool(_COMPETITOR_HOST.match(url))


def mask_text(text: str) -> str:
    """Competitor links removed (a Markdown link keeps its text), then names replaced."""
    text = _MARKDOWN_LINK.sub(
        lambda m: m.group(1) if is_competitor_url(m.group(2)) else m.group(0), text
    )
    text = _BARE_URL.sub(lambda m: "" if is_competitor_url(m.group(0)) else m.group(0), text)
    text = _TERM.sub(lambda m: _TERMS_CASEFOLDED[m.group(0).casefold()], text)
    return _NAME.sub(lambda m: _CASEFOLDED[m.group(1).casefold()], text)


def mask(value: Any) -> Any:
    """`value` (decoded JSON) with every competitor name and site masked."""
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, list):
        return [mask(item) for item in value]
    if isinstance(value, dict):
        return {
            key: None
            if key in _URL_KEYS and isinstance(item, str) and is_competitor_url(item)
            else mask(item)
            for key, item in value.items()
        }
    return value


def real_name(name: str) -> str:
    """The stored name behind an alias (a real name is returned as is)."""
    return REAL_NAMES.get(name, name)
