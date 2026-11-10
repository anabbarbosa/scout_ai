"""The weekly summary for Marketing: `scout report` (guide Step 6).

Signals are those detected in the 7 days before the report date. Recommendations
(guide Step 7) are the top ones of the latest `scout recommend` run in that week, up to
the report date, still proposed or approved. Funnel, spend and cost
metrics are monthly, because that is how the internal data is aggregated: the report
uses the latest month that has Marketing spend (so a month still in progress is never
compared with a full one) against the month before. Competitive deals are counted by
close date, for that month and for the year to date.

Pipeline value per dollar is not available: the tables count opportunities but do not
store their amounts. The report shows opportunities per $1,000 of spend instead.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scout_ai.db.models import (
    Competitor,
    CompetitorTier,
    DealCompetition,
    DealOutcome,
    FunnelMetric,
    MarketingSpend,
    Recommendation,
    RecommendationStatus,
    Region,
    Signal,
    WeeklySummary,
)

SIGNAL_DAYS = 7
TOP_RECOMMENDATIONS = 5
RECOMMENDATIONS_LABEL = (
    "Built on the synthetic demo data: they show how the system works, not what the "
    "business should do."
)
DEMO_LABEL = (
    "Internal numbers in this summary come from the synthetic demo dataset, generated "
    "from real HubSpot and Marketing patterns: they show how the report works, not the "
    "real business. Competitor signals are real."
)
REGION_LABELS = {
    Region.NORTH_AMERICA: "North America",
    Region.BRAZIL: "Brazil",
    Region.LATAM: "Latam",
    Region.EMEA: "EMEA",
    Region.APAC: "APAC",
    Region.OTHER: "Other",
}


@dataclass
class FunnelCounts:
    mqls: int = 0
    opportunities: int = 0
    deals_won: int = 0
    spend: Decimal | None = None  # only known per region

    @property
    def cost_per_mql(self) -> Decimal | None:
        return _ratio(self.spend, self.mqls)

    @property
    def opportunities_per_1k(self) -> Decimal | None:
        if not self.spend:
            return None
        return Decimal(self.opportunities) * 1000 / self.spend

    @property
    def cac(self) -> Decimal | None:
        """Marketing spend per deal won."""
        return _ratio(self.spend, self.deals_won)


@dataclass(frozen=True)
class CompetitorDeals:
    name: str
    tier: CompetitorTier
    won_month: int
    lost_month: int
    won_ytd: int
    lost_ytd: int
    open_now: int

    @property
    def win_rate_ytd(self) -> float | None:
        closed = self.won_ytd + self.lost_ytd
        return self.won_ytd / closed if closed else None


@dataclass(frozen=True)
class SignalItem:
    competitor: str
    tier: CompetitorTier
    type: str
    title: str
    summary: str
    relevance: str | None
    url: str


@dataclass(frozen=True)
class RecommendationItem:
    id: int
    action: str
    status: str
    priority: float
    impact: int
    cost: int
    effort: int
    confidence: int
    evidence: list[dict[str, Any]]
    created_at: datetime


@dataclass
class WeeklyReport:
    report_date: date
    signals_since: date
    month: date | None  # None when there is no spend data yet
    previous_month: date | None
    signals: list[SignalItem] = field(default_factory=list)
    recommendations: list[RecommendationItem] = field(default_factory=list)
    regions: dict[str, tuple[FunnelCounts, FunnelCounts]] = field(default_factory=dict)
    channels: dict[str, tuple[FunnelCounts, FunnelCounts]] = field(default_factory=dict)
    competitors: list[CompetitorDeals] = field(default_factory=list)


def build_weekly_report(session: Session, report_date: date) -> WeeklyReport:
    since = report_date - timedelta(days=SIGNAL_DAYS)
    month = session.scalar(select(func.max(MarketingSpend.period)))
    previous = _previous_month(month) if month else None
    report = WeeklyReport(report_date, since, month, previous)
    report.signals = _signals(session, since, report_date)
    report.recommendations = _recommendations(session, since, report_date)
    if month is not None and previous is not None:
        report.regions = _by_region(session, month, previous)
        report.channels = _by_channel(session, month, previous)
        report.competitors = _competitor_deals(session, month)
    return report


def _previous_month(month: date) -> date:
    return (month.replace(day=1) - timedelta(days=1)).replace(day=1)


def _ratio(amount: Decimal | None, count: int) -> Decimal | None:
    return amount / count if amount is not None and count else None


def _signals(session: Session, since: date, until: date) -> list[SignalItem]:
    start = datetime.combine(since, time(), UTC)
    end = datetime.combine(until, time(), UTC)
    rows = session.execute(
        select(Signal, Competitor)
        .join(Competitor)
        .where(Signal.detected_at >= start, Signal.detected_at < end)
        .order_by(Competitor.tier, Competitor.name, Signal.detected_at, Signal.id)
    ).all()
    return [
        SignalItem(c.name, c.tier, s.type, s.title, s.summary, s.relevance, s.url) for s, c in rows
    ]


def _recommendations(session: Session, since: date, until: date) -> list[RecommendationItem]:
    """The top recommendations of the latest run in the window, still open or approved."""
    start = datetime.combine(since, time(), UTC)
    end = datetime.combine(until + timedelta(days=1), time(), UTC)
    window = (
        Recommendation.status.in_([RecommendationStatus.PROPOSED, RecommendationStatus.APPROVED]),
        Recommendation.created_at >= start,
        Recommendation.created_at < end,
    )
    latest = session.scalar(select(func.max(Recommendation.created_at)).where(*window))
    if latest is None:
        return []
    run_start = datetime.combine(latest.date(), time(), UTC)
    rows = session.scalars(
        select(Recommendation)
        .where(*window, Recommendation.created_at >= run_start)
        .order_by(Recommendation.priority.desc(), Recommendation.id)
        .limit(TOP_RECOMMENDATIONS)
    )
    return [
        RecommendationItem(
            r.id,
            r.action,
            r.status,
            r.priority,
            r.impact,
            r.cost,
            r.effort,
            r.confidence,
            r.evidence,
            r.created_at,
        )
        for r in rows
    ]


def _funnel(session: Session, key: str, month: date) -> dict[str, FunnelCounts]:
    column = getattr(FunnelMetric, key)
    rows = session.execute(
        select(
            column,
            func.sum(FunnelMetric.mqls),
            func.sum(FunnelMetric.opportunities),
            func.sum(FunnelMetric.deals_won),
        )
        .where(FunnelMetric.period == month)
        .group_by(column)
    ).all()
    return {
        _label(value): FunnelCounts(int(m or 0), int(o or 0), int(w or 0))
        for value, m, o, w in rows
    }


def _label(value: object) -> str:
    if isinstance(value, Region):
        return REGION_LABELS[value]
    return str(value) or "(no channel)"


def _spend(session: Session, month: date) -> dict[str, Decimal]:
    rows = session.execute(
        select(MarketingSpend.region, func.sum(MarketingSpend.amount))
        .where(MarketingSpend.period == month)
        .group_by(MarketingSpend.region)
    ).all()
    return {REGION_LABELS[region]: Decimal(amount) for region, amount in rows}


def _pairs(
    current: dict[str, FunnelCounts], previous: dict[str, FunnelCounts]
) -> dict[str, tuple[FunnelCounts, FunnelCounts]]:
    keys = sorted(set(current) | set(previous))
    return {k: (current.get(k, FunnelCounts()), previous.get(k, FunnelCounts())) for k in keys}


def _by_region(
    session: Session, month: date, previous: date
) -> dict[str, tuple[FunnelCounts, FunnelCounts]]:
    pairs = _pairs(_funnel(session, "region", month), _funnel(session, "region", previous))
    for period, index in ((month, 0), (previous, 1)):
        for region, amount in _spend(session, period).items():
            pairs.setdefault(region, (FunnelCounts(), FunnelCounts()))[index].spend = amount
    # Regions with spend but no funnel rows still belong in the table.
    return dict(sorted(pairs.items()))


def _by_channel(
    session: Session, month: date, previous: date
) -> dict[str, tuple[FunnelCounts, FunnelCounts]]:
    pairs = _pairs(_funnel(session, "channel", month), _funnel(session, "channel", previous))
    return dict(sorted(pairs.items(), key=lambda item: -item[1][0].mqls))


def _competitor_deals(session: Session, month: date) -> list[CompetitorDeals]:
    next_month = (month + timedelta(days=32)).replace(day=1)
    year_start = month.replace(month=1)
    counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for deal in session.scalars(select(DealCompetition)):
        bucket = counts[deal.competitor_id]
        if deal.outcome is DealOutcome.OPEN:
            bucket["open"] += 1
            continue
        if deal.closed_at is None or not year_start <= deal.closed_at < next_month:
            continue
        bucket[f"{deal.outcome}_ytd"] += 1
        if deal.closed_at >= month:
            bucket[f"{deal.outcome}_month"] += 1
    competitors = session.scalars(
        select(Competitor).order_by(Competitor.tier, Competitor.name)
    ).all()
    return [
        CompetitorDeals(
            c.name,
            c.tier,
            counts[c.id]["won_month"],
            counts[c.id]["lost_month"],
            counts[c.id]["won_ytd"],
            counts[c.id]["lost_ytd"],
            counts[c.id]["open"],
        )
        for c in competitors
    ]


def title(report: WeeklyReport) -> str:
    return f"Scout AI weekly summary: {report.report_date:%Y-%m-%d}"


def save_summary(session: Session, report: WeeklyReport, markdown: str) -> WeeklySummary:
    """Store the summary for the notifications page; a second run the same day replaces it."""
    summary = session.scalar(
        select(WeeklySummary).where(WeeklySummary.report_date == report.report_date)
    )
    if summary is None:
        summary = WeeklySummary(report_date=report.report_date)
        session.add(summary)
    summary.title = title(report)
    summary.month = report.month
    summary.signal_count = len(report.signals)
    summary.markdown = markdown
    session.flush()
    return summary


# --- Markdown ---


def render_markdown(report: WeeklyReport) -> str:
    lines = [
        f"# {title(report)}",
        "",
        f"> **Demo data.** {DEMO_LABEL}",
        "",
    ]
    lines += _render_signals(report)
    lines += _render_recommendations(report)
    if report.month is None:
        lines += ["## Funnel, spend and competitive deals", "", "No internal data loaded yet."]
        return "\n".join(lines) + "\n"
    for table in tables(report):
        lines += _render_table(table)
    return "\n".join(lines) + "\n"


def _render_signals(report: WeeklyReport) -> list[str]:
    lines = [f"## Competitor signals ({signals_window(report)})", ""]
    if not report.signals:
        return [*lines, "No new signals this week.", ""]
    by_competitor: dict[str, list[SignalItem]] = defaultdict(list)
    for signal in report.signals:
        by_competitor[signal.competitor].append(signal)
    for name, signals in by_competitor.items():
        tier = "top 3" if signals[0].tier is CompetitorTier.TOP3 else "watchlist"
        lines += [f"### {name} ({tier}): {len(signals)} new", ""]
        for s in signals:
            lines.append(f"- **[{s.type.replace('_', ' ')}] [{s.title}]({s.url})**  ")
            lines.append(f"  {s.summary}")
            if s.relevance:
                lines.append(f"  *Why it matters:* {s.relevance}")
        lines.append("")
    return lines


def _render_recommendations(report: WeeklyReport) -> list[str]:
    if not report.recommendations:
        return ["## Recommendations", "", "No recommendations this week.", ""]
    generated = report.recommendations[0].created_at
    lines = [
        f"## Recommendations (generated {generated:%Y-%m-%d})",
        "",
        f"> {RECOMMENDATIONS_LABEL}",
        "",
    ]
    for number, r in enumerate(report.recommendations, 1):
        status = " (approved)" if r.status == RecommendationStatus.APPROVED else ""
        lines.append(f"{number}. **{r.action}**{status}  ")
        lines.append(
            f"   Priority {r.priority:.2f}: impact {r.impact}, confidence {r.confidence}, "
            f"cost {r.cost}, effort {r.effort}. Evidence:"
        )
        for item in r.evidence:
            label = item.get("label") or item.get("ref", "")
            name = f"[{label}]({item['url']})" if item.get("url") else str(label)
            lines.append(f"   - {name}: {item.get('note', '')}")
    lines += [
        "",
        "Priority is impact x confidence / (cost + effort), computed from the 1 to 5 scores.",
        "",
    ]
    return lines


@dataclass(frozen=True)
class Table:
    """A report table: a header, rows of formatted cells and an optional note."""

    title: str
    header: list[str]
    rows: list[list[str]]
    note: str = ""
    total_row: bool = False  # the last row is a total


def region_table(report: WeeklyReport) -> Table:
    total_now, total_before = FunnelCounts(spend=Decimal(0)), FunnelCounts(spend=Decimal(0))
    rows = []
    for region, (now, before) in report.regions.items():
        rows.append(_region_row(region, now, before))
        for total, part in ((total_now, now), (total_before, before)):
            total.mqls += part.mqls
            total.opportunities += part.opportunities
            total.deals_won += part.deals_won
            total.spend = (total.spend or Decimal(0)) + (part.spend or Decimal(0))
    rows.append(_region_row("Total", total_now, total_before))
    return Table(
        f"Funnel and spend by region ({_period(report)})",
        [
            "Region",
            "MQLs",
            "Opportunities",
            "Deals won",
            "Spend",
            "Cost per MQL",
            "Opps per $1k",
            "Marketing CAC",
        ],
        rows,
        "Each cell shows this month, then the change against the previous month. Spend is "
        "only known per region. Leads and SQLs are not tracked yet, so the funnel starts at "
        "MQLs. Pipeline value per dollar is not available (opportunity amounts are not "
        "stored), so opportunities per $1,000 of spend stand in for it.",
        total_row=True,
    )


def _region_row(name: str, now: FunnelCounts, before: FunnelCounts) -> list[str]:
    return [
        name,
        _count(now.mqls, before.mqls),
        _count(now.opportunities, before.opportunities),
        _count(now.deals_won, before.deals_won),
        _money_change(now.spend, before.spend),
        _money_change(now.cost_per_mql, before.cost_per_mql),
        _number_change(now.opportunities_per_1k, before.opportunities_per_1k),
        _money_change(now.cac, before.cac),
    ]


def channel_table(report: WeeklyReport) -> Table:
    rows = []
    for channel, (now, before) in report.channels.items():
        rate_now = now.opportunities / now.mqls if now.mqls else None
        rate_before = before.opportunities / before.mqls if before.mqls else None
        rows.append(
            [
                channel,
                _count(now.mqls, before.mqls),
                _count(now.opportunities, before.opportunities),
                _count(now.deals_won, before.deals_won),
                _rate(rate_now, rate_before),
            ]
        )
    return Table(
        f"Funnel by channel ({_period(report)})",
        ["Channel", "MQLs", "Opportunities", "Deals won", "MQL to opportunity"],
        rows,
        "Opportunities and deals are counted in the month they were created or won, so a "
        "channel can show opportunities in a month with no MQLs.",
    )


def competitor_table(report: WeeklyReport) -> Table:
    month = report.month
    assert month is not None
    rows = []
    for c in report.competitors:
        tier = "" if c.tier is CompetitorTier.TOP3 else " (watchlist)"
        rate = f"{c.win_rate_ytd:.0%}" if c.win_rate_ytd is not None else "-"
        rows.append(
            [
                f"{c.name}{tier}",
                str(c.won_month),
                str(c.lost_month),
                str(c.won_ytd),
                str(c.lost_ytd),
                rate,
                str(c.open_now),
            ]
        )
    return Table(
        f"Deals against competitors (closed in {month:%B %Y}, and {month:%Y} to date)",
        [
            "Competitor",
            "Won (month)",
            "Lost (month)",
            "Won (YTD)",
            "Lost (YTD)",
            "Win rate (YTD)",
            "Open now",
        ],
        rows,
    )


def tables(report: WeeklyReport) -> list[Table]:
    if report.month is None:
        return []
    return [region_table(report), channel_table(report), competitor_table(report)]


def _period(report: WeeklyReport) -> str:
    assert report.month is not None and report.previous_month is not None
    return f"{report.month:%B %Y} vs {report.previous_month:%B %Y}"


def signals_window(report: WeeklyReport) -> str:
    last_day = report.report_date - timedelta(days=1)
    return f"{report.signals_since:%b %d} to {last_day:%b %d}"


def _render_table(table: Table) -> list[str]:
    lines = [
        f"## {table.title}",
        "",
        "| " + " | ".join(table.header) + " |",
        "|---|" + "---:|" * (len(table.header) - 1),
    ]
    for index, row in enumerate(table.rows):
        cells = list(row)
        if table.total_row and index == len(table.rows) - 1:
            cells[0] = f"**{cells[0]}**"
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    if table.note:
        lines += [table.note, ""]
    return lines


def _pct_change(now: Decimal | float, before: Decimal | float | None) -> str:
    if not before:
        return ""
    change = (Decimal(str(now)) - Decimal(str(before))) / Decimal(str(before))
    return f" ({change:+.0%})"


def _count(now: int, before: int) -> str:
    return f"{now:,}{_pct_change(now, before)}"


def _money_change(now: Decimal | None, before: Decimal | None) -> str:
    if now is None:
        return "-"
    return f"${now:,.0f}{_pct_change(now, before)}"


def _number_change(now: Decimal | None, before: Decimal | None) -> str:
    if now is None:
        return "-"
    return f"{now:.1f}{_pct_change(now, before)}"


def _rate(now: float | None, before: float | None) -> str:
    if now is None:
        return "-"
    if before is None:
        return f"{now:.0%}"
    return f"{now:.0%} ({(now - before) * 100:+.0f} pp)"
