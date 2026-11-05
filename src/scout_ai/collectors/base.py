"""The interface shared by every collector (guide Step 3.1)."""

import hashlib
from typing import Protocol

from scout_ai.db.models import Snapshot, Source


class CollectorError(Exception):
    """A source could not be collected; the run reports it and moves on to the next source."""


class BlockedError(CollectorError):
    """The site does not let us fetch this URL (robots.txt, HTTP 401 or 403). Not retried."""


class Collector(Protocol):
    def fetch(self, source: Source) -> Snapshot:
        """Fetch the source and return an unsaved snapshot of its cleaned text."""
        ...


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_snapshot(source: Source, text: str) -> Snapshot:
    if not text.strip():
        raise CollectorError("no text found; the page may need a browser to render")
    return Snapshot(source_id=source.id, content_hash=content_hash(text), raw_text=text)
