"""The grant calendar: which grants appear, research timeline events, and the .ics export."""
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import agenda, db
from app.main import app

AGENCY = "deq"
SOON = (date.today() + timedelta(days=40)).isoformat()
STEP = (date.today() + timedelta(days=10)).isoformat()
RESEARCH = {
    "key_dates": [
        {"label": "Applications due", "date": SOON, "source": None},          # restates the deadline: dropped
        {"label": "Informational webinar", "date": STEP, "source": {"doc_id": "1", "doc_name": "NOFO.pdf", "page": 4}},
        {"label": "Letters of intent, in words only", "date": None, "source": None},
    ],
    "timeline": [
        {"title": "Confirm SAM.gov registration", "detail": "Takes weeks; start now.", "date": STEP, "source": None},
        {"title": "Draft narrative", "detail": "", "date": None, "source": None},
    ],
    "contact": None,
}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def seeded(client):
    with db.session() as conn:
        for t in ("decisions", "research"):
            conn.execute(f"DELETE FROM {t} WHERE agency_id=?", (AGENCY,))
        conn.execute("DELETE FROM opportunities WHERE id LIKE 'cal:%'")
        rows = [("cal:pursue", "posted", SOON, "Wetland, Restoration; Grants"),  # punctuation that .ics must escape
                ("cal:save", "forecasted", SOON, "Forecast grant"),
                ("cal:dismiss", "posted", SOON, "Dismissed grant"),
                ("cal:nodate", "posted", None, "Rolling grant")]
        for oid, status, close, title in rows:
            conn.execute("INSERT INTO opportunities(id, source, title, status, close_date, number, url) VALUES(?,?,?,?,?,?,?)",
                         (oid, "test", title, status, close, "EPA-1", "https://www.grants.gov/x"))
        for oid, action in (("cal:pursue", "save"), ("cal:pursue", "pursue"), ("cal:save", "save"),
                            ("cal:dismiss", "dismiss"), ("cal:nodate", "pursue")):
            conn.execute("INSERT INTO decisions(agency_id, opportunity_id, action) VALUES(?,?,?)", (AGENCY, oid, action))
        conn.execute("INSERT INTO research(opportunity_id, agency_id, result, created_at) VALUES(?,?,?,?)",
                     ("cal:pursue", AGENCY, json.dumps(RESEARCH), "2026-11-01T00:00:00+00:00"))


def test_tracked_grants_and_research_events(client, seeded):
    r = client.post("/api/calendar", json={"agency_id": AGENCY})
    assert r.status_code == 200
    data = r.json()
    by_id = {e["id"]: e for e in data["events"]}
    assert set(by_id) == {"deadline:cal:pursue", "deadline:cal:save", "key:cal:pursue:1", "step:cal:pursue:0"}
    assert by_id["deadline:cal:pursue"]["kind"] == "deadline" and by_id["deadline:cal:pursue"]["status"] == "pursue"
    assert by_id["deadline:cal:save"]["kind"] == "forecast"
    assert by_id["key:cal:pursue:1"]["source"]["page"] == 4
    assert data["undated_steps"] == 1 and data["researched_count"] == 1 and data["grant_count"] == 3
    assert [e["date"] for e in data["events"]] == sorted(e["date"] for e in data["events"])


def test_layers_can_be_turned_off(client, seeded):
    data = client.post("/api/calendar", json={"agency_id": AGENCY, "include": ["save"]}).json()
    assert [e["id"] for e in data["events"]] == ["deadline:cal:save"]


def test_recommended_layer_uses_search(client, seeded):
    data = client.post("/api/calendar", json={"agency_id": AGENCY, "include": ["recommended"],
                                              "filters": {"min_score": 0, "include_lower_scores": True}}).json()
    assert data["events"] and {e["status"] for e in data["events"]} == {"recommended"}
    bad = client.post("/api/calendar", json={"agency_id": AGENCY, "include": ["recommended"], "filters": {"min_score": "lots"}})
    assert bad.status_code == 422


def test_single_grant_calendar_ignores_status(client, seeded):
    data = client.post("/api/calendar", json={"agency_id": AGENCY, "opportunity_id": "cal:dismiss", "include": ["research"]}).json()
    assert [e["id"] for e in data["events"]] == ["deadline:cal:dismiss"]
    assert client.post("/api/calendar", json={"agency_id": AGENCY, "opportunity_id": "cal:nope"}).status_code == 404


def test_validation(client, seeded):
    assert client.post("/api/calendar", json={"agency_id": "nope"}).status_code == 404
    assert client.post("/api/calendar", json={"agency_id": AGENCY, "include": ["everything"]}).status_code == 422


def test_ics_export(client, seeded):
    r = client.post("/api/calendar.ics", json={"agency_id": AGENCY})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    assert 'filename="grant-calendar-deq.ics"' in r.headers["content-disposition"]
    text = r.text
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert text.count("BEGIN:VEVENT") == 4 and text.count("BEGIN:VALARM") == 4  # two reminders per deadline
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))
    unfolded = text.replace("\r\n ", "")
    assert f"DTSTART;VALUE=DATE:{SOON.replace('-', '')}" in unfolded
    assert "SUMMARY:Due: Wetland\\, Restoration\\; Grants" in unfolded
    assert "UID:deadline:cal:pursue.deq@nc-grants-matchmaker" in unfolded
    assert "Source: NOFO.pdf\\, page 4." in unfolded


def test_single_grant_ics_filename(client, seeded):
    r = client.post("/api/calendar.ics", json={"agency_id": AGENCY, "opportunity_id": "cal:pursue", "include": ["research"]})
    assert 'filename="grant-cal-pursue.ics"' in r.headers["content-disposition"]
    assert r.text.count("BEGIN:VEVENT") == 3


def test_fold_keeps_multibyte_characters_whole():
    line = "DESCRIPTION:" + "é" * 80
    folded = agenda._fold(line)
    assert all(len(part.encode()) <= 75 for part in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == line
