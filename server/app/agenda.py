"""The calendar: deadlines for the grants an agency is tracking, plus the dated steps from saved
in-depth research, as JSON events for the website and as an iCalendar (.ics) file for Outlook,
Google Calendar or Apple Calendar.

Event ids are stable (built from the grant and the item), so they double as iCalendar UIDs:
importing a newer file can update events instead of adding copies, in apps that honor UIDs.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from . import config, db
from .agencies import AGENCY_BY_ID
from .search import Filters, latest_decisions, search

STATUSES = ("pursue", "save", "recommended")
STATUS_LABEL = {"pursue": "Pursuing", "save": "Saved", "recommended": "Recommended"}
KIND_LABEL = {"deadline": "Applications due", "forecast": "Expected due date (forecast)",
              "key_date": "Key date", "step": "Suggested step"}
# A research "key date" on the closing date that just restates the deadline.
DUE_RE = re.compile(r"\b(due|deadline|clos|submi)", re.I)
ICS_PAST_DAYS = 30  # older events are left out of the .ics file


def _iso(value) -> str | None:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat() if value else None
    except ValueError:
        return None


def _grant(o: dict) -> dict:
    return {k: o.get(k) for k in ("id", "title", "number", "url", "federal_agency", "status", "close_date")}


def grant_events(o: dict, status: str, research: dict | None) -> tuple[list[dict], int]:
    """Events for one grant, and how many research steps had no date (so aren't on the calendar)."""
    grant, events, undated = _grant(o), [], 0

    def add(uid, day, kind, title, detail=None, source=None):
        events.append({"id": uid, "date": day, "kind": kind, "title": title, "detail": detail or None,
                       "source": source if isinstance(source, dict) else None, "status": status, "opportunity": grant})

    close = _iso(o.get("close_date"))
    if close:
        forecast = o.get("status") == "forecasted"
        note = ((research or {}).get("contact") or {}).get("deadline_note")
        add(f"deadline:{o['id']}", close, "forecast" if forecast else "deadline", KIND_LABEL["forecast" if forecast else "deadline"],
            note or ("The agency's estimate; the real date is set when the notice is posted." if forecast else "The listing's closing date."))
    if research:
        for i, k in enumerate(research.get("key_dates") or []):
            day = _iso(k.get("date"))
            if not day:
                continue
            if day == close and DUE_RE.search(k.get("label") or ""):
                continue
            add(f"key:{o['id']}:{i}", day, "key_date", (k.get("label") or "Key date").strip(), None, k.get("source"))
        for i, t in enumerate(research.get("timeline") or []):
            day = _iso(t.get("date"))
            if not day:
                undated += 1
                continue
            add(f"step:{o['id']}:{i}", day, "step", (t.get("title") or "Step").strip(), t.get("detail"), t.get("source"))
    return events, undated


def _tracked(agency_id: str, statuses: set[str], filters: Filters | None, recommended_limit: int,
             opportunity_id: str = "") -> list[tuple[dict, str]]:
    """(opportunity, status) for the grants that belong on this agency's calendar."""
    with db.session() as conn:
        decisions = [dict(r) for r in conn.execute("SELECT * FROM decisions WHERE agency_id=? ORDER BY id", (agency_id,))]
    latest = latest_decisions(decisions)

    if opportunity_id:  # one grant, whatever its status
        with db.session() as conn:
            row = conn.execute("SELECT * FROM opportunities WHERE id=?", (opportunity_id,)).fetchone()
        if not row:
            raise LookupError("Unknown opportunity")
        decision = latest.get(opportunity_id)
        return [(db.row_to_dict(row), decision["action"] if decision else "recommended")]

    wanted = [oid for oid, d in latest.items() if d["action"] in statuses]
    out = []
    if wanted:
        with db.session() as conn:
            marks = ",".join("?" * len(wanted))
            rows = {r["id"]: db.row_to_dict(r) for r in conn.execute(f"SELECT * FROM opportunities WHERE id IN ({marks})", wanted)}
        out = [(rows[oid], latest[oid]["action"]) for oid in wanted if oid in rows]  # expired grants are gone
    if "recommended" in statuses and filters is not None:
        f = Filters.from_dict({**filters.to_dict(), "agency_id": agency_id, "view": "recommended", "sort": "score"})
        for r in search(f, limit=recommended_limit)["results"]:
            out.append((r["opportunity"], "recommended"))
    return out


def build(agency_id: str, include: list[str], filters: Filters | None = None, recommended_limit: int = 15,
          opportunity_id: str = "") -> dict:
    statuses = {s for s in include if s in STATUSES}
    with_research = "research" in include
    grants = _tracked(agency_id, statuses, filters, recommended_limit, opportunity_id)
    research = {}
    if with_research and grants:
        ids = [o["id"] for o, _ in grants]
        with db.session() as conn:
            marks = ",".join("?" * len(ids))
            for r in conn.execute(f"SELECT opportunity_id, result FROM research WHERE agency_id=? AND opportunity_id IN ({marks})",
                                  [agency_id, *ids]):
                try:
                    research[r["opportunity_id"]] = json.loads(r["result"])
                except (TypeError, ValueError):
                    pass
    events, undated = [], 0
    for o, status in grants:
        ev, n = grant_events(o, status, research.get(o["id"]))
        events.extend(ev)
        undated += n
    events.sort(key=lambda e: (e["date"], ["deadline", "forecast", "key_date", "step"].index(e["kind"]), e["opportunity"]["title"]))
    return {
        "agency": {k: AGENCY_BY_ID[agency_id][k] for k in ("id", "short", "name")},
        "events": events,
        "grant_count": len(grants),
        "researched_count": len(research),
        "undated_steps": undated,
        "today": date.today().isoformat(),
    }


# ---------------- iCalendar ----------------

def _escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Lines longer than 75 octets continue on the next line after a space (RFC 5545 3.1)."""
    if len(line.encode("utf-8")) <= 75:
        return line
    parts, cur, limit = [], b"", 75
    for ch in line:  # never split a multi-byte character
        b = ch.encode("utf-8")
        if len(cur) + len(b) > limit:
            parts.append(cur)
            cur, limit = b"", 74  # the leading space counts toward the next line
        cur += b
    parts.append(cur)
    return "\r\n ".join(part.decode("utf-8") for part in parts)


def grant_link(agency_id: str, opportunity_id: str) -> str:
    return f"{config.PUBLIC_BASE_URL}/?{urlencode({'agency': agency_id, 'opp': opportunity_id})}"


def to_ics(data: dict, name: str) -> str:
    agency_id = data["agency"]["id"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cutoff = (date.today() - timedelta(days=ICS_PAST_DAYS)).isoformat()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//GrantNC//Grant calendar//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_escape(name)}"]
    for e in data["events"]:
        if e["date"] < cutoff:
            continue
        o, day = e["opportunity"], date.fromisoformat(e["date"])
        prefix = {"deadline": "Due", "forecast": "Due (forecast)", "key_date": "Date", "step": "Step"}[e["kind"]]
        summary = f"{prefix}: {o['title']}" if e["kind"] in ("deadline", "forecast") else f"{prefix}: {e['title']} ({o['title']})"
        detail = [f"{KIND_LABEL[e['kind']]} for {o['title']}" + (f" ({o['number']})" if o.get("number") else "") + ".",
                  f"Status: {STATUS_LABEL.get(e['status'], e['status'])}."]
        if e["kind"] in ("key_date", "step"):
            detail.insert(1, e["title"] + (f": {e['detail']}" if e.get("detail") else ""))
            detail.append("Suggested by AI from the notice documents. Check it against the notice.")
        elif e.get("detail"):
            detail.insert(1, e["detail"])
        if e.get("source"):
            detail.append(f"Source: {e['source'].get('doc_name')}, page {e['source'].get('page')}.")
        detail.append(f"In GrantNC: {grant_link(agency_id, o['id'])}")
        if o.get("url"):
            detail.append(f"Listing: {o['url']}")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{_escape(e['id'])}.{agency_id}@nc-grants-matchmaker",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
            f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_escape(summary)}",
            f"DESCRIPTION:{_escape(chr(10).join(detail))}",
            f"URL:{grant_link(agency_id, o['id'])}",
            "TRANSP:TRANSPARENT",  # all-day reminders shouldn't block the day as busy
            f"CATEGORIES:{_escape(KIND_LABEL[e['kind']])}",
        ]
        if e["kind"] in ("deadline", "forecast"):
            for before, label in (("-P14D", "two weeks"), ("-P3D", "three days")):
                lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:{before}",
                          f"DESCRIPTION:{_escape(o['title'])} is due in {label}", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
