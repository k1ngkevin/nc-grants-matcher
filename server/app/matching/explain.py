"""Plain-language "why this fits" rationales.

Default: a deterministic template built from the score signals (instant, free, no AI).
If Azure OpenAI chat is configured, the top matches get an LLM-written rationale that is
grounded only in the opportunity text and the agency profile, then cached.
"""
import hashlib
import logging

import requests

from .. import config, db

log = logging.getLogger(__name__)


def money(n: int | None) -> str:
    if not n:
        return "amount not listed"
    if n >= 1_000_000:
        return f"${n / 1_000_000:.1f}M".replace(".0M", "M")
    return f"${n / 1000:.0f}K"


def template_rationale(agency: dict, result: dict) -> str:
    s, o = result["signals"], result["opportunity"]
    bits = []
    if s["matched_project"]:
        bits.append(f"Closely related to your active project “{s['matched_project']['title']}.”")
    if s["matched_keywords"]:
        kws = ", ".join(s["matched_keywords"][:3])
        bits.append(f"Lines up with {agency['short']}'s work on {kws}.")
    elif s["mission_fit"] >= 0.5:
        bits.append(f"Its purpose overlaps with {agency['short']}'s mission.")
    if s["matched_program"]:
        bits.append(f"Funded under program {s['matched_program']}, a federal program {agency['short']} typically draws from.")
    if o.get("nc_past_funding"):
        bits.append(f"NC recipients received {money(o['nc_past_funding'])} under this program last fiscal year.")
    bits.append(s["eligibility"] + ".")
    if not bits[:-1]:
        bits.insert(0, "A weaker topical match. Worth a quick look only if the program area is new for you.")
    return " ".join(bits)


def _cache_key(agency_id: str, opp_id: str, projects: list[dict]) -> str:
    proj = "|".join(sorted(p["title"] for p in projects))
    return hashlib.sha1(f"{agency_id}:{opp_id}:{proj}".encode()).hexdigest()


def llm_rationale(agency: dict, result: dict, projects: list[dict]) -> str | None:
    if not config.USE_AZURE_CHAT:
        return None
    o = result["opportunity"]
    key = _cache_key(agency["id"], o["id"], projects)
    with db.session() as conn:
        row = conn.execute("SELECT text FROM explanations WHERE cache_key=?", (key,)).fetchone()
    if row:
        return row["text"]
    project_lines = "\n".join(f"- {p['title']}: {p['description'][:300]}" for p in projects[:8]) or "(none logged)"
    prompt = (
        f"Agency: {agency['name']}\nMission: {agency['mission']}\nActive projects:\n{project_lines}\n\n"
        f"Federal opportunity: {o['title']} ({o.get('federal_agency')})\n"
        f"Description: {(o.get('description') or '')[:2500]}\n\n"
        "In 2-3 short sentences for a busy state grants coordinator, explain why this opportunity does or does not "
        "fit this agency's goals and active projects. Name the specific project if one fits. Use only the facts above; "
        "if the fit is weak, say so plainly. No preamble."
    )
    url = (f"{config.AZURE_OPENAI_ENDPOINT}/openai/deployments/{config.AZURE_CHAT_DEPLOYMENT}"
           f"/chat/completions?api-version={config.AZURE_OPENAI_API_VERSION}")
    try:
        r = requests.post(url, headers={"api-key": config.AZURE_OPENAI_KEY}, timeout=30, json={
            "messages": [{"role": "system", "content": "You help North Carolina state agencies triage federal grants. Be concise and factual."},
                         {"role": "user", "content": prompt}],
            "max_tokens": 180, "temperature": 0.2})
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.warning("LLM rationale failed, using template: %s", e)
        return None
    with db.session() as conn:
        conn.execute("INSERT OR REPLACE INTO explanations(cache_key, text) VALUES(?, ?)", (key, text))
    return text
