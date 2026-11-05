"""Single pages (homepage, segment, comparison, pricing): store the cleaned visible text."""

from scout_ai.collectors.base import make_snapshot
from scout_ai.collectors.http import PoliteClient
from scout_ai.collectors.text import clean_text
from scout_ai.db.models import Snapshot, Source


class PageCollector:
    def __init__(self, http: PoliteClient) -> None:
        self.http = http

    def fetch(self, source: Source) -> Snapshot:
        page = self.http.get(source.url)
        return make_snapshot(source, clean_text(page.text))
