from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from scout_ai.db.models import Region
from scout_ai.integrations.marketing_csv import (
    ENCODING,
    MarketingCSVError,
    find_export,
    read_mqls,
    read_spend,
    to_region,
)

# Made-up values in the layout of the real exports (which hold personal data and stay in
# data/raw/). The em dash checks the cp1252 encoding.
REGION_HEADER = (
    ",Region,Spend,MQLs,Cost / MQL,Pipeline Opps,MQL ? Pipeline,Pipeline Created,"
    "Pipeline / Spend,Closed Won $,New Logos,Marketing CAC,"
)
SPEND_CSV = f"""\
,,,,,,,,,,,,
,Monthly MQL Cost — Detail,,,,,,,,,,,
,,,,,,,,,,,,
,January 2026,,,,,,,,,,,
,INVESTMENT,,DEMAND,,PIPELINE,,,,RETURN,,,
{REGION_HEADER}
,North America,"$1,000",10,$100,1,10.0%,"$5,000",5.0x,$0,0,-,
,Brazil,$500,5,$100,0,0.0%,$0,0.0x,$0,0,-,
,Total,"$1,500",15,$100,1,6.7%,"$5,000",3.3x,$0,0,-,
,,,,,,,,,,,,
,February 2026,,,,,,,,,,,
,INVESTMENT,,DEMAND,,PIPELINE,,,,RETURN,,,
{REGION_HEADER}
,EMEA,"$2,250",3,$750,0,0.0%,$0,0.0x,$0,0,-,
,Total,"$2,250",3,$750,0,0.0%,$0,0.0x,$0,0,-,
,,,,,,,,,,,,
"""

MQL_HEADER = (
    "Most Recent Date: MQL,utm_source,Sales Region,First Name,Last Name,Contact ID,"
    "Original Source Drill-Down 1,Original Source Drill-Down 2,Original Source,Contact ID,"
    "Company ID,UTM Source,Month,CID (text lookup)\n"
)
MQL_CSV = MQL_HEADER + (
    "2026-01-05,google,NA,Ana,Teste,1,search_intent,lims,Paid Search,1,10,Google,1,1\n"
    # same contact and date, another company: counted once
    "2026-01-05,google,NA,Ana,Teste,1,search_intent,lims,Paid Search,1,11,Google,1,1\n"
    "2026-02-10,(No value),BRAZIL,Júlia,Exemplo,2,(No value),(No value),Direct Traffic,2,12,"
    "Direct,2,2\n"
    "2026-03-01,fb,id,Bo,Sample,3,webinar,fb,Paid Social,3,13,Facebook,3,3\n"
)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding=ENCODING, newline="")
    return path


def test_read_spend_skips_titles_headers_and_totals(tmp_path: Path) -> None:
    rows = read_spend(_write(tmp_path, "spend.csv", SPEND_CSV))
    assert [(r.period, r.region, r.amount) for r in rows] == [
        (date(2026, 1, 1), Region.NORTH_AMERICA, Decimal(1000)),
        (date(2026, 1, 1), Region.BRAZIL, Decimal(500)),
        (date(2026, 2, 1), Region.EMEA, Decimal(2250)),
    ]


def test_read_spend_rejects_a_file_without_blocks(tmp_path: Path) -> None:
    with pytest.raises(MarketingCSVError):
        read_spend(_write(tmp_path, "empty.csv", ",,,\n,Something else,,\n"))


def test_read_mqls_dedupes_and_keeps_no_personal_data(tmp_path: Path) -> None:
    mqls = read_mqls(_write(tmp_path, "mqls.csv", MQL_CSV))
    assert len(mqls) == 3
    assert mqls[0].mql_date == date(2026, 1, 5)
    assert mqls[0].region is Region.NORTH_AMERICA
    assert (mqls[0].channel, mqls[0].campaign) == ("Paid Search", "search_intent")
    assert mqls[1].campaign == ""  # "(No value)"
    assert mqls[2].region is Region.OTHER  # unknown spelling
    assert set(vars(mqls[0])) == {"mql_date", "region", "channel", "campaign"}


def test_read_mqls_rejects_unexpected_columns(tmp_path: Path) -> None:
    with pytest.raises(MarketingCSVError):
        read_mqls(_write(tmp_path, "bad.csv", "Date,Region\n2026-01-01,NA\n"))


@pytest.mark.parametrize(
    ("raw", "region"),
    [
        ("North America", Region.NORTH_AMERICA),
        (" NA ", Region.NORTH_AMERICA),
        ("BRAZIL", Region.BRAZIL),
        ("APAC", Region.APAC),
        ("ROW", Region.OTHER),
    ],
)
def test_to_region(raw: str, region: Region) -> None:
    assert to_region(raw) is region


def test_find_export_needs_exactly_one_match(tmp_path: Path) -> None:
    with pytest.raises(MarketingCSVError, match="nothing"):
        find_export(tmp_path, "*MQL Count*.csv")
    expected = _write(tmp_path, "MQL Cost(MQL Count ).csv", MQL_CSV)
    assert find_export(tmp_path, "*MQL Count*.csv") == expected
