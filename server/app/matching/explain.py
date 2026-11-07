"""Plain-language "why this fits" rationales.

Default: a deterministic template built from the score signals (instant, free, no AI).
If Azure OpenAI chat is configured, the top matches get an LLM-written rationale that is
grounded only in the opportunity text and the agency profile, then cached.
"""
import hashlib
import logging
import time

import requests

from .. import config, db

log = logging.getLogger(__name__)
CHAT_COOLDOWN_SECONDS = 300
_chat_down_until = 0.0  # time.monotonic() until which AI rationales are skipped after a failure
# Request shapes, tried in order until one is accepted (then remembered). Older chat models
# (gpt-4o, gpt-4.1) take max_tokens + temperature; reasoning models (gpt-5 family, o-series)
# reject both and need max_completion_tokens, which also covers their hidden reasoning tokens.
REQUEST_SHAPES = [
    {"max_tokens": 180, "temperature": 0.2},
    {"max_completion_tokens": 2000, "reasoning_effort": "low"},
    {"max_completion_tokens": 2000},
]
_shape = 0


def available() -> bool:
    """AI rationales are configured and not cooling down after a failure."""
    return config.USE_AZURE_CHAT and time.monotonic() >= _chat_down_until


def _error_text(r: requests.Response) -> str:
    try:
        err = r.json()["error"]
        return f"{err.get('code') or ''} {err.get('message') or ''}".strip()
    except (ValueError, KeyError, TypeError, AttributeError):
        return r.text[:300]


def _chat(messages: list[dict]) -> str:
    """One chat completion. Raises RuntimeError with a readable reason on failure."""
    global _shape
    url = (f"{config.AZURE_OPENAI_ENDPOINT}/openai/deployments/{config.AZURE_CHAT_DEPLOYMENT}"
           f"/chat/completions?api-version={config.AZURE_OPENAI_API_VERSION}")
    for i in range(_shape, len(REQUEST_SHAPES)):
        try:
            r = requests.post(url, headers={"api-key": config.AZURE_OPENAI_KEY}, timeout=30,
                              json={"messages": messages, **REQUEST_SHAPES[i]})
        except requests.RequestException as e:
            raise RuntimeError(f"couldn't reach {config.AZURE_OPENAI_ENDPOINT}: {e}") from e
        if r.status_code == 400 and i + 1 < len(REQUEST_SHAPES):
            continue  # most likely a parameter this model doesn't take; try the next shape
        if r.status_code == 404 and "DeploymentNotFound" in r.text:
            raise RuntimeError(f"{config.AZURE_OPENAI_ENDPOINT} has no deployment named '{config.AZURE_CHAT_DEPLOYMENT}'. "
                               "Deploy a chat model under that name in Azure AI Foundry, or fix AZURE_CHAT_DEPLOYMENT.")
        if not r.ok:
            raise RuntimeError(f"Azure OpenAI returned {r.status_code}: {_error_text(r)}")
        try:
            text = (r.json()["choices"][0]["message"].get("content") or "").strip()
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"unreadable response: {e}") from e
        if not text:
            raise RuntimeError("the model returned no text (it may have used its whole token budget on reasoning)")
        _shape = i
        return text
    raise AssertionError("unreachable")


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
    """AI-written rationale, or None (use the template) if AI isn't configured or isn't working."""
    global _chat_down_until
    if not available():
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
    try:
        text = _chat([{"role": "system", "content": "You help North Carolina state agencies triage federal grants. Be concise and factual."},
                      {"role": "user", "content": prompt}])
    except Exception as e:
        _chat_down_until = time.monotonic() + CHAT_COOLDOWN_SECONDS
        log.error("AI explanations failed, so rule-based ones are used for the next %d minutes: %s",
                  CHAT_COOLDOWN_SECONDS // 60, e)
        return None
    with db.session() as conn:
        conn.execute("INSERT OR REPLACE INTO explanations(cache_key, text) VALUES(?, ?)", (key, text))
    return text
