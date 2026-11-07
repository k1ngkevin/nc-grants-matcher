/* Common federal grant terms in plain English. Used to explain jargon anywhere in a research report,
   including reports saved before the AI started writing its own glossary. The AI's glossary for a notice
   is merged on top, so program-specific meanings win. Keep each meaning short and true everywhere. */
export const GRANT_TERMS = {
  NOFO: "Notice of Funding Opportunity: the official announcement with the grant's rules and how to apply.",
  NOFA: "Notice of Funding Availability: another name for the official funding announcement.",
  FOA: "Funding Opportunity Announcement: another name for the official funding announcement.",
  RFA: "Request for Applications: the announcement asking for applications.",
  RFP: "Request for Proposals: the announcement asking for proposals.",
  LOI: "Letter of Intent: a short note telling the federal agency you plan to apply. Sometimes required.",
  "SAM.gov": "The federal website where your organization must register, and renew every year, before it can receive federal money.",
  UEI: "Unique Entity ID: the 12-character ID SAM.gov gives your organization. It replaced the DUNS number in 2022.",
  DUNS: "An older 9-digit organization ID. Federal grants switched to the UEI from SAM.gov in April 2022.",
  "Grants.gov": "The federal website where most grant applications are found and submitted.",
  AOR: "Authorized Organization Representative: the person allowed to submit applications for your organization in Grants.gov.",
  EIN: "Employer Identification Number: your organization's federal tax ID.",
  ALN: "Assistance Listing Number: the number for a federal program, like 66.460. It used to be called a CFDA number.",
  CFDA: "Catalog of Federal Domestic Assistance: the old name for Assistance Listings. CFDA numbers are now ALNs.",
  "SF-424": "The standard federal application cover form.",
  "SF-424A": "The standard federal budget form for programs that aren't construction.",
  "SF-LLL": "The form for disclosing lobbying activities.",
  "SF-425": "The Federal Financial Report: the standard form for reporting how grant money was spent.",
  "cost share": "The part of the project cost your agency must pay itself, in cash or in-kind. Also called a match.",
  "cost sharing": "The part of the project cost your agency must pay itself, in cash or in-kind. Also called a match.",
  "matching funds": "Money (or in-kind value) your agency must put in alongside the federal grant.",
  "in-kind": "Non-cash contributions, like staff time, equipment or space, counted at their dollar value.",
  "indirect costs": "Overhead such as rent, HR and accounting that supports many projects, charged at an approved rate.",
  NICRA: "Negotiated Indirect Cost Rate Agreement: your organization's federally approved overhead rate.",
  "de minimis rate": "A flat overhead rate organizations without a negotiated rate may charge instead (15% of certain direct costs since October 2024).",
  "Uniform Guidance": "The federal rules for managing grants (2 CFR 200): allowable costs, purchasing, audits and reports.",
  "2 CFR 200": "The Uniform Guidance: the federal rules for managing grants, from allowable costs to audits.",
  "period of performance": "The dates during which the grant money can be spent.",
  "pass-through entity": "An organization, often a state agency, that receives federal money and passes it on to others as subawards.",
  subaward: "Part of a grant that the main recipient passes to another organization to carry out some of the work.",
  subrecipient: "An organization that gets a subaward from the main grant recipient and must follow the same federal rules.",
  "cooperative agreement": "A grant where the federal agency stays closely involved in the work.",
  "Single Audit": "A yearly audit required when an organization spends $1 million or more in federal awards in a year.",
  MOU: "Memorandum of Understanding: a written agreement between partners about who does what.",
  MOA: "Memorandum of Agreement: a written agreement between partners about who does what.",
  "program officer": "The federal staff member who runs the grant program and answers applicants' questions.",
  "allowable costs": "Expenses the grant rules let you pay for with grant money.",
  "pre-award costs": "Costs paid before the grant starts. Only allowed if the notice or the federal agency approves them.",
  supplant: "To use grant money to replace funding you already have. Most grants forbid it: grants must add to existing funding.",
  "formula grant": "Money split among states by a set formula in law, not by competition.",
  "discretionary grant": "A competitive grant: the federal agency picks winners from the applications.",
  "lead agency": "The one agency designated, often by the governor, to apply for and run a program for the whole state.",
  "State Lead Agency": "The one agency the governor designates to apply for and run this program for the state.",
  "lead agencies": "Agencies designated, often by the governor, to apply for and run a program for the whole state.",
  "State and Territorial Lead Agency": "The one agency each governor designates to apply for and run this program for the state.",
  "State and Territorial Lead Agencies": "The one agency each governor designates to apply for and run this program for the state. Other agencies usually apply through it.",
  NEPA: "National Environmental Policy Act: requires an environmental review before federal money funds a project.",
  "Davis-Bacon": "A law requiring local prevailing wages on federally funded construction projects.",
  BABA: "Build America, Buy America: iron, steel and building materials in federally funded infrastructure must be made in the US unless waived.",
  "Build America, Buy America": "Iron, steel and building materials in federally funded infrastructure must be made in the US unless waived.",
  // Federal agencies that often appear in notices.
  NPS: "National Park Service, part of the US Department of the Interior.",
  EPA: "US Environmental Protection Agency.",
  FEMA: "Federal Emergency Management Agency, part of the US Department of Homeland Security.",
  DHS: "US Department of Homeland Security.",
  HUD: "US Department of Housing and Urban Development.",
  USDA: "US Department of Agriculture.",
  USDOT: "US Department of Transportation.",
  FHWA: "Federal Highway Administration, part of the US Department of Transportation.",
  FTA: "Federal Transit Administration, part of the US Department of Transportation.",
  NOAA: "National Oceanic and Atmospheric Administration, part of the US Department of Commerce.",
  EDA: "Economic Development Administration, part of the US Department of Commerce.",
  DOJ: "US Department of Justice.",
  HHS: "US Department of Health and Human Services.",
  DOE: "US Department of Energy.",
  USFWS: "US Fish and Wildlife Service, part of the US Department of the Interior.",
  NSF: "National Science Foundation.",
  NIH: "National Institutes of Health.",
  NEH: "National Endowment for the Humanities.",
  NEA: "National Endowment for the Arts.",
  IMLS: "Institute of Museum and Library Services.",
  SAMHSA: "Substance Abuse and Mental Health Services Administration, part of HHS.",
  CDC: "Centers for Disease Control and Prevention.",
  OMB: "Office of Management and Budget: the White House office that writes federal grant rules.",
  LWCF: "Land and Water Conservation Fund: a federal program that pays for parks and outdoor recreation.",
  ORLP: "Outdoor Recreation Legacy Partnership: a competitive part of the Land and Water Conservation Fund for parks in urban areas.",
};

const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const isAcronym = (term) => /^[A-Z0-9.\-]+$/.test(term) && /[A-Z]/.test(term);
const NOTHING = /(?!)/g;

/** One lookup from the built-in terms plus a notice's own glossary (which wins on conflicts). */
export function buildGlossary(aiTerms = []) {
  const map = new Map(Object.entries(GRANT_TERMS).map(([t, m]) => [t.toLowerCase(), { term: t, meaning: m, ai: false }]));
  for (const { term, meaning } of aiTerms || []) {
    if (term && meaning) map.set(term.toLowerCase(), { term, meaning, ai: true });
  }
  const terms = [...map.values()].sort((a, b) => b.term.length - a.term.length);
  const alt = (list, plural) => list.map((t) => escape(t.term) + (plural ? "s?" : "")).join("|");
  const acronyms = terms.filter((t) => isAcronym(t.term));
  const phrases = terms.filter((t) => !isAcronym(t.term));
  // Acronyms match exactly ("MOU", never "mou"); phrases match any case, with an optional plural "s".
  return {
    terms,
    map,
    acronymRe: acronyms.length ? new RegExp(`(?<![\\w-])(?:${alt(acronyms)})(?![\\w-])`, "g") : NOTHING,
    phraseRe: phrases.length ? new RegExp(`(?<![\\w-])(?:${alt(phrases, true)})(?![\\w-])`, "gi") : NOTHING,
  };
}

function lookup(glossary, raw) {
  const key = raw.toLowerCase();
  return glossary.map.get(key) || glossary.map.get(key.replace(/s$/, ""));
}

/** Split text into pieces: [{ text, entry? }]. Each term is marked once per text, longest match first. */
export function findTerms(text, glossary) {
  if (!text) return [{ text: "" }];
  const hits = [];
  for (const re of [glossary.acronymRe, glossary.phraseRe]) {
    for (const m of text.matchAll(re)) {
      const entry = lookup(glossary, m[0]);
      if (entry) hits.push({ start: m.index, end: m.index + m[0].length, entry });
    }
  }
  hits.sort((a, b) => a.start - b.start || b.end - a.end);
  const out = [];
  const used = new Set();
  let last = 0;
  for (const h of hits) {
    if (h.start < last || used.has(h.entry.term)) continue; // overlaps a longer match, or already explained
    used.add(h.entry.term);
    if (h.start > last) out.push({ text: text.slice(last, h.start) });
    out.push({ text: text.slice(h.start, h.end), entry: h.entry });
    last = h.end;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}
