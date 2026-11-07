import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, fmtDate, store } from "./api.js";
import GrantCard from "./GrantCard.jsx";
import { EmailSignup, Filters, ImproveMatches } from "./Sidebar.jsx";
import Glossary from "./Glossary.jsx";

const ALL_TIMING = ["urgent", "standard", "later", "forecasted"];
const DEFAULT_MIN_SCORE = 40;
const TABS = [
  ["recommended", "Recommended"],
  ["save", "Saved"],
  ["pursue", "Pursuing"],
  ["dismiss", "Dismissed"],
];

function defaultFilters(floor) {
  return {
    min_award: floor,
    timing: ALL_TIMING,
    q: "",
    federal_agency: "",
    no_match_only: false,
    include_unknown_amount: true,
    min_score: DEFAULT_MIN_SCORE,
    sort: "score",
  };
}

function urlParams() {
  const p = new URLSearchParams(window.location.search);
  return { agency: p.get("agency"), opp: p.get("opp") };
}

export default function App() {
  const [meta, setMeta] = useState(null);
  const [metaError, setMetaError] = useState("");
  const [agencyId, setAgencyId] = useState(() => urlParams().agency || store.get("agency"));
  const [filters, setFilters] = useState(null);
  const [view, setView] = useState("recommended");
  const [limit, setLimit] = useState(25);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showGlossary, setShowGlossary] = useState(false);
  const [focusOpp, setFocusOpp] = useState(() => urlParams().opp);
  const [debouncedQ, setDebouncedQ] = useState("");
  const reqId = useRef(0);

  useEffect(() => {
    api.meta()
      .then((m) => {
        setMeta(m);
        setFilters({ ...defaultFilters(m.financial_floor), ...store.get("filters", {}), q: "" });
        if (agencyId && !m.agencies.some((a) => a.id === agencyId)) setAgencyId(null);
      })
      .catch((e) => setMetaError(e.message));
  }, []);

  useEffect(() => {
    if (!filters) return;
    const t = setTimeout(() => setDebouncedQ(filters.q), 300);
    return () => clearTimeout(t);
  }, [filters?.q]);

  useEffect(() => {
    if (filters) store.set("filters", { ...filters, q: "" });
  }, [filters]);

  useEffect(() => {
    if (!agencyId) return;
    store.set("agency", agencyId);
    const p = new URLSearchParams(window.location.search);
    p.set("agency", agencyId);
    if (!focusOpp) p.delete("opp");
    window.history.replaceState(null, "", `?${p.toString()}`);
  }, [agencyId, focusOpp]);

  const searchBody = useMemo(
    () => (filters && agencyId ? { ...filters, q: debouncedQ, agency_id: agencyId, view } : null),
    [filters, debouncedQ, agencyId, view]
  );

  const load = useCallback(async () => {
    if (!searchBody) return;
    const id = ++reqId.current;
    setLoading(true);
    setError("");
    try {
      const body = focusOpp ? { ...searchBody, min_score: 0, timing: ALL_TIMING } : searchBody;
      const res = await api.search({ ...body, limit: focusOpp ? 200 : limit });
      if (id === reqId.current) setData(res);
    } catch (e) {
      if (id === reqId.current) setError(e.message);
    } finally {
      if (id === reqId.current) setLoading(false);
    }
  }, [searchBody, limit, focusOpp]);

  useEffect(() => {
    load();
  }, [load]);

  const agency = meta?.agencies.find((a) => a.id === agencyId);

  const decide = async (opp, action, extra = {}) => {
    const res = await api.decide({ agency_id: agencyId, opportunity_id: opp.id, action, ...extra });
    await load();
    return res;
  };

  const exportCsv = async () => {
    const blob = await api.exportCsv({ ...searchBody, limit: 200 });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `grants-${agencyId}-${view}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  if (metaError) return <div className="center-msg">Couldn't reach the server: {metaError}</div>;
  if (!meta || !filters) return <div className="center-msg">Loading…</div>;

  const last = meta.last_ingest;
  const counts = data?.counts || {};

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href="/" onClick={(e) => { e.preventDefault(); setAgencyId(null); setData(null); store.set("agency", null); window.history.replaceState(null, "", "/"); }}>
            <span className="logo">$</span>
            <span>
              <strong>NC Federal Funds Matchmaker</strong>
              <small>Federal grants your agency can win, ranked and explained</small>
            </span>
          </a>
          <div className="topbar-right">
            {last && (
              <span className="freshness" title={`Source: ${last.source}`}>
                Updated {fmtDate(last.as_of)} · {meta.opportunity_count} open grants
              </span>
            )}
            <button className="link-btn light" onClick={() => setShowGlossary(true)}>What do grant types mean?</button>
          </div>
        </div>
      </header>

      {meta.sample_data && (
        <div className="sample-banner">
          <strong>Demo mode:</strong> showing a labeled SAMPLE dataset, not live grants. Run <code>python -m app.ingest</code> on a
          machine with internet access to load live Grants.gov data.
        </div>
      )}

      {!agency ? (
        <Landing meta={meta} onPick={(id) => { setAgencyId(id); setView("recommended"); }} />
      ) : (
        <main className="layout">
          <aside className="sidebar">
            <div className="card">
              <label className="field-label" htmlFor="agency-select">Your agency</label>
              <select id="agency-select" className="big-select" value={agencyId}
                onChange={(e) => { setAgencyId(e.target.value); setView("recommended"); setLimit(25); setFocusOpp(null); }}>
                {meta.agencies.map((a) => (
                  <option key={a.id} value={a.id}>{a.name} ({a.short})</option>
                ))}
              </select>
            </div>
            <Filters
              meta={meta}
              filters={filters}
              facets={data?.facets}
              onChange={(f) => { setFilters(f); setLimit(25); setFocusOpp(null); }}
              onReset={() => setFilters(defaultFilters(meta.financial_floor))}
              defaultMinScore={DEFAULT_MIN_SCORE}
            />
            <EmailSignup meta={meta} agency={agency} filters={{ ...filters, q: debouncedQ }} />
            <ImproveMatches agency={agency} onChanged={load} />
          </aside>

          <section className="results">
            <nav className="tabs" role="tablist">
              {TABS.map(([key, label]) => (
                <button key={key} role="tab" aria-selected={view === key} className={`tab ${view === key ? "active" : ""}`}
                  onClick={() => { setView(key); setLimit(25); setFocusOpp(null); }}>
                  {label} <span className="tab-count">{counts[key] ?? "–"}</span>
                </button>
              ))}
            </nav>

            <div className="toolbar">
              <div className="summary">
                {data ? <Summary data={data} view={view} agency={agency} /> : " "}
              </div>
              <div className="toolbar-actions">
                <label className="sort">
                  Sort
                  <select value={filters.sort} onChange={(e) => setFilters({ ...filters, sort: e.target.value })}>
                    <option value="score">Best match</option>
                    <option value="deadline">Deadline (soonest)</option>
                    <option value="amount">Largest award</option>
                  </select>
                </label>
                <button className="btn ghost small" onClick={exportCsv} disabled={!data?.total}>Download CSV</button>
              </div>
            </div>

            {focusOpp && (
              <div className="notice">
                Showing the grant from your email. <button className="link-btn" onClick={() => setFocusOpp(null)}>Show all results</button>
              </div>
            )}
            {error && <div className="error">{error}</div>}
            {loading && !data && <div className="skeleton-list">{[0, 1, 2].map((i) => <div key={i} className="skeleton" />)}</div>}

            {data && data.results.length === 0 && !loading && (
              <EmptyState view={view} filters={filters} setFilters={setFilters} agency={agency} />
            )}

            <div className={`card-list ${loading ? "dim" : ""}`}>
              {data?.results
                .filter((r) => !focusOpp || r.opportunity.id === focusOpp)
                .map((r) => (
                  <GrantCard key={r.opportunity.id} result={r} view={view} agency={agency} meta={meta}
                    onDecide={decide} startExpanded={r.opportunity.id === focusOpp} />
                ))}
            </div>

            {data && !focusOpp && data.total > data.results.length && (
              <button className="btn ghost wide" onClick={() => setLimit(limit + 25)}>
                Show more ({data.total - data.results.length} more)
              </button>
            )}

            <p className="footnote">
              Scores are recommendations. Your team makes every decision. Only grants that are still open, at least{" "}
              {`$${(meta.financial_floor / 1000).toFixed(0)}K`}, and open to{" "}
              {agency.applicant === "higher_ed" ? "public colleges and universities" : "state governments"} are shown.
            </p>
          </section>
        </main>
      )}

      {showGlossary && <Glossary meta={meta} onClose={() => setShowGlossary(false)} />}
    </>
  );
}

function Summary({ data, view, agency }) {
  const urgent = data.facets.timing.urgent;
  if (view !== "recommended") {
    const label = { save: "saved", pursue: "being pursued", dismiss: "dismissed" }[view];
    return <span><strong>{data.total}</strong> grants {label} by {agency.short}</span>;
  }
  return (
    <span>
      <strong>{data.total}</strong> grants match {agency.short}
      {urgent > 0 && <> · <span className="urgent-text">{urgent} closing within 14 days</span></>}
    </span>
  );
}

function EmptyState({ view, filters, setFilters, agency }) {
  if (view !== "recommended") {
    return <div className="empty">Nothing here yet. Use the buttons on a grant to {view === "save" ? "save it for later" : view === "pursue" ? "mark it Pursue" : "dismiss it"}.</div>;
  }
  return (
    <div className="empty">
      <p><strong>No strong matches for {agency.short} with these filters.</strong></p>
      <p>Try widening the filters or showing weaker matches. Adding your active projects (left) also helps the matching.</p>
      <div className="empty-actions">
        {filters.min_score > 0 && <button className="btn" onClick={() => setFilters({ ...filters, min_score: 0 })}>Show weaker matches</button>}
        {filters.q && <button className="btn ghost" onClick={() => setFilters({ ...filters, q: "" })}>Clear search</button>}
      </div>
    </div>
  );
}

function Landing({ meta, onPick }) {
  const [choice, setChoice] = useState("");
  return (
    <main className="landing">
      <div className="landing-card">
        <h1>Find federal grants your agency can win</h1>
        <p className="lead">Pick your agency. We'll show open federal grants you're eligible for, ranked by fit, with a plain-English reason for each one.</p>
        <form onSubmit={(e) => { e.preventDefault(); if (choice) onPick(choice); }}>
          <label className="field-label" htmlFor="landing-agency">Which agency are you with?</label>
          <div className="landing-row">
            <select id="landing-agency" className="big-select" value={choice} onChange={(e) => setChoice(e.target.value)} autoFocus>
              <option value="">Choose your agency…</option>
              {meta.agencies.map((a) => (
                <option key={a.id} value={a.id}>{a.name} ({a.short})</option>
              ))}
            </select>
            <button className="btn primary big" disabled={!choice}>Show my grants</button>
          </div>
        </form>
        <ul className="promises">
          <li><span>✓</span> Only grants your agency is <b>eligible</b> for</li>
          <li><span>✓</span> No expired deadlines, no micro-grants under ${(meta.financial_floor / 1000).toFixed(0)}K</li>
          <li><span>✓</span> A clear reason for every match, and you make the call</li>
          <li><span>✓</span> Optional email with the top grants each week</li>
        </ul>
      </div>
    </main>
  );
}
