"""Competitor collectors, one per kind of source (guide Step 3).

Reviews have no collector: Capterra's robots.txt disallows everything and G2's terms
forbid automated access, so review sources are reported as unsupported until an allowed
access path (a paid data agreement or a manual export) is chosen.
"""

from scout_ai.collectors.base import Collector
from scout_ai.collectors.http import PoliteClient
from scout_ai.collectors.listing import ListingCollector
from scout_ai.collectors.page import PageCollector
from scout_ai.db.models import SourceType


def build_collectors(http: PoliteClient) -> dict[SourceType, Collector]:
    page = PageCollector(http)
    listing = ListingCollector(http)
    return {
        SourceType.HOMEPAGE: page,
        SourceType.SEGMENT_PAGE: page,
        SourceType.COMPARISON: page,
        SourceType.PRICING: page,
        SourceType.BLOG: listing,
        SourceType.PRESS: listing,
        SourceType.EVENTS: listing,
        SourceType.JOBS: listing,
    }
