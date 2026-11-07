from datetime import date, timedelta

from app import guardrails
from app.agencies import AGENCY_BY_ID
from app.ingest import grantsgov
from app.ingest.sample_data import sample_records
from app.normalize import parse_date, timing_category

TODAY = date.today()


def opp(**kw):
    base = {"status": "posted", "close_date": (TODAY + timedelta(days=30)).isoformat(), "award_ceiling": 500_000,
            "eligibility_codes": ["00"]}
    base.update(kw)
    return base


def test_expired_dropped():
    assert guardrails.check(opp(close_date=(TODAY - timedelta(days=1)).isoformat())) == (False, "deadline passed")


def test_closing_today_kept():
    assert guardrails.check(opp(close_date=TODAY.isoformat()))[0]


def test_financial_floor():
    assert not guardrails.check(opp(award_ceiling=49_999))[0]
    assert guardrails.check(opp(award_ceiling=50_000))[0]
    # average award (total / count) is used when no ceiling is listed
    assert not guardrails.check(opp(award_ceiling=None, estimated_funding=400_000, expected_awards=10))[0]
    # users can raise the floor but never lower it
    assert guardrails.check(opp(award_ceiling=60_000), floor=10_000)[0]
    assert not guardrails.check(opp(award_ceiling=60_000), floor=100_000)[0]


def test_unknown_amount_toggle():
    o = opp(award_ceiling=None)
    assert guardrails.check(o)[0]
    assert not guardrails.check(o, include_unknown_amount=False)[0]


def test_strict_eligibility():
    state, uni = AGENCY_BY_ID["deq"], AGENCY_BY_ID["unc"]
    assert not guardrails.check(opp(eligibility_codes=["12"]))[0]           # nonprofits only
    assert guardrails.check(opp(eligibility_codes=["00"]), state)[0]
    assert not guardrails.check(opp(eligibility_codes=["06"]), state)[0]   # universities only -> not DEQ
    assert guardrails.check(opp(eligibility_codes=["06"]), uni)[0]
    assert not guardrails.check(opp(eligibility_codes=["00"]), uni)[0]     # state govts only -> not UNC


def test_timing_categories():
    d = lambda n: (TODAY + timedelta(days=n)).isoformat()
    assert timing_category("posted", d(0)) == "urgent"
    assert timing_category("posted", d(14)) == "urgent"
    assert timing_category("posted", d(15)) == "standard"
    assert timing_category("posted", d(60)) == "standard"
    assert timing_category("posted", d(61)) == "later"
    assert timing_category("forecasted", d(90)) == "forecasted"
    assert timing_category("forecasted", None) == "forecasted"
    assert timing_category("posted", d(-1)) is None


def test_parse_date_formats():
    assert parse_date("12/15/2025") == "2025-12-15"
    assert parse_date("Feb 28, 2025 12:00:00 AM EST") == "2025-02-28"
    assert parse_date("2025-02-28-00-00-00") == "2025-02-28"
    assert parse_date("") is None


def test_grantsgov_normalize_shape():
    hit, detail = sample_records()[0]
    o = grantsgov.normalize(hit, detail)
    assert o["id"] == "grantsgov:9001"
    assert o["aln_numbers"] == ["66.460"]
    assert o["eligibility_codes"] == ["00"]
    assert o["award_ceiling"] == 3_500_000
    assert o["cost_sharing"] == 1
    assert o["competition"] == "M"
    assert "<p>" not in o["description"]
