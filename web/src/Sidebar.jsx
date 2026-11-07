import { useEffect, useState } from "react";
import { api, store } from "./api.js";

const TIMING = [
  ["urgent", "Closes within 14 days"],
  ["standard", "Closes in 15–60 days"],
  ["later", "Closes in 60+ days"],
  ["forecasted", "Forecast (coming soon)"],
];
const AWARD_OPTIONS = [50_000, 100_000, 250_000, 1_000_000, 5_000_000];

export function Filters({ meta, filters, facets, onChange, onReset, defaultMinScore }) {
  const set = (patch) => onChange({ ...filters, ...patch });
  const toggleTiming = (t) => {
    const next = filters.timing.includes(t) ? filters.timing.filter((x) => x !== t) : [...filters.timing, t];
    set({ timing: next.length ? next : [t] });
  };
  const depts = Object.entries(facets?.federal_agency || {});

  return (
    <div className="card">
      <div className="card-head">
        <h2>Filters</h2>
        <button className="link-btn" onClick={onReset}>Reset</button>
      </div>

      <label className="field-label" htmlFor="kw">Search</label>
      <input id="kw" type="search" placeholder="e.g. broadband, flood, literacy" value={filters.q} onChange={(e) => set({ q: e.target.value })} />

      <label className="field-label" htmlFor="min-award">Minimum award</label>
      <select id="min-award" value={filters.min_award} onChange={(e) => set({ min_award: Number(e.target.value) })}>
        {AWARD_OPTIONS.filter((v) => v >= meta.financial_floor).map((v) => (
          <option key={v} value={v}>{v >= 1_000_000 ? `$${v / 1_000_000}M` : `$${v / 1000}K`} or more</option>
        ))}
      </select>

      <fieldset>
        <legend className="field-label">Deadline</legend>
        {TIMING.map(([key, label]) => (
          <label key={key} className="check">
            <input type="checkbox" checked={filters.timing.includes(key)} onChange={() => toggleTiming(key)} />
            <span className={`dot timing-${key}`} />
            {label}
            <span className="count">{facets?.timing?.[key] ?? ""}</span>
          </label>
        ))}
      </fieldset>

      <label className="field-label" htmlFor="fed">Federal department</label>
      <select id="fed" value={filters.federal_agency} onChange={(e) => set({ federal_agency: e.target.value })}>
        <option value="">All departments</option>
        {filters.federal_agency && !depts.some(([d]) => d === filters.federal_agency) && (
          <option value={filters.federal_agency}>{filters.federal_agency}</option>
        )}
        {depts.map(([d, n]) => (
          <option key={d} value={d}>{d} ({n})</option>
        ))}
      </select>

      <fieldset>
        <legend className="field-label">More options</legend>
        <label className="check">
          <input type="checkbox" checked={filters.no_match_only} onChange={(e) => set({ no_match_only: e.target.checked })} />
          No matching funds required
        </label>
        <label className="check">
          <input type="checkbox" checked={filters.include_unknown_amount} onChange={(e) => set({ include_unknown_amount: e.target.checked })} />
          Include grants with no amount listed
        </label>
        <label className="check">
          <input type="checkbox" checked={filters.min_score === 0} onChange={(e) => set({ min_score: e.target.checked ? 0 : defaultMinScore })} />
          Show weaker matches too
        </label>
      </fieldset>
    </div>
  );
}

export function EmailSignup({ meta, agency, filters }) {
  const [email, setEmail] = useState(() => store.get("email", ""));
  const [frequency, setFrequency] = useState("weekly");
  const [topN, setTopN] = useState(10);
  const [state, setState] = useState({ status: "idle" });

  useEffect(() => setState({ status: "idle" }), [agency.id]);

  const { sort, ...searchFilters } = filters;
  const body = { email: email.trim(), agency_id: agency.id, frequency, top_n: topN, filters: searchFilters };

  const submit = async (e) => {
    e.preventDefault();
    setState({ status: "busy" });
    try {
      const res = await api.subscribe(body);
      store.set("email", email.trim());
      setState({ status: "done", res });
    } catch (err) {
      setState({ status: "error", error: err.message });
    }
  };

  const preview = async () => {
    try {
      const html = await api.previewEmail({ ...body, email: body.email || "preview@example.gov" });
      const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
      window.open(url, "_blank", "noopener");
    } catch (err) {
      setState({ status: "error", error: err.message });
    }
  };

  if (state.status === "done") {
    const r = state.res;
    return (
      <div className="card email-card done">
        <h2>✓ You're set</h2>
        {r.confirmed ? (
          <p>We'll email the top {topN} grants for {agency.short} to <b>{r.email}</b> {frequency}. The first one was just sent.</p>
        ) : (
          <p>Check <b>{r.email}</b> for a confirmation link. Alerts start once you confirm.</p>
        )}
        {!r.email_enabled && (
          <p className="hint">
            Demo server: email isn't configured, so messages are saved to the server's outbox folder.
            {r.dev_confirm_url && (<> <a href={r.dev_confirm_url} target="_blank" rel="noopener noreferrer">Confirm now (demo)</a></>)}
          </p>
        )}
        <button className="link-btn" onClick={() => setState({ status: "idle" })}>Add another</button>
      </div>
    );
  }

  return (
    <form className="card email-card" onSubmit={submit}>
      <h2>📬 Email me the top grants</h2>
      <p className="hint">Get the best matches for {agency.short} with the filters you've set. Unsubscribe anytime.</p>
      <label className="field-label" htmlFor="sub-email">Work email</label>
      <input id="sub-email" type="email" required placeholder="you@agency.nc.gov" value={email} onChange={(e) => setEmail(e.target.value)} />
      <div className="two-col">
        <div>
          <label className="field-label" htmlFor="sub-freq">How often</label>
          <select id="sub-freq" value={frequency} onChange={(e) => setFrequency(e.target.value)}>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="biweekly">Every 2 weeks</option>
            <option value="monthly">Monthly</option>
          </select>
        </div>
        <div>
          <label className="field-label" htmlFor="sub-n">How many</label>
          <select id="sub-n" value={topN} onChange={(e) => setTopN(Number(e.target.value))}>
            {[5, 10, 15, 25].map((n) => <option key={n} value={n}>Top {n}</option>)}
          </select>
        </div>
      </div>
      {meta.allowed_email_domains.length > 0 && <p className="hint">Allowed: {meta.allowed_email_domains.join(", ")}</p>}
      {state.status === "error" && <div className="error small">{state.error}</div>}
      <button className="btn primary wide" disabled={state.status === "busy"}>{state.status === "busy" ? "Subscribing…" : "Subscribe"}</button>
      <button type="button" className="link-btn center" onClick={preview}>Preview the email</button>
    </form>
  );
}

export function ImproveMatches({ agency, onChanged }) {
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState([]);
  const [docs, setDocs] = useState([]);
  const [p, setP] = useState({ title: "", description: "" });
  const [d, setD] = useState({ title: "", content: "" });
  const [error, setError] = useState("");

  const refresh = () => {
    api.projects(agency.id).then(setProjects).catch(() => {});
    api.documents(agency.id).then(setDocs).catch(() => {});
  };
  useEffect(refresh, [agency.id]);

  const run = async (fn) => {
    setError("");
    try {
      await fn();
      refresh();
      onChanged();
    } catch (e) {
      setError(e.message);
    }
  };

  const readFile = (file) => {
    if (!file) return;
    if (!/\.(txt|md|csv)$/i.test(file.name)) {
      setError("Upload a .txt or .md file, or paste the text. (For a PDF, copy and paste its text.)");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setD({ title: d.title || file.name.replace(/\.[^.]+$/, ""), content: String(reader.result).slice(0, 300000) });
    reader.readAsText(file);
  };

  return (
    <div className="card">
      <button className="card-head toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <h2>Improve your matches</h2>
        <span className="muted">{projects.length} project{projects.length === 1 ? "" : "s"} · {docs.length} plan{docs.length === 1 ? "" : "s"} {open ? "▲" : "▼"}</span>
      </button>
      {!open && <p className="hint">Tell us what {agency.short} is working on and matches get sharper for everyone at your agency.</p>}
      {open && (
        <>
          {error && <div className="error small">{error}</div>}
          <h3 className="mini-h">Active projects</h3>
          <ul className="item-list">
            {projects.map((x) => (
              <li key={x.id}>
                <span title={x.description}>{x.title}</span>
                <button className="link-btn danger" onClick={() => run(() => api.deleteProject(agency.id, x.id))} aria-label={`Remove ${x.title}`}>Remove</button>
              </li>
            ))}
          </ul>
          <form onSubmit={(e) => { e.preventDefault(); run(async () => { await api.addProject(agency.id, p); setP({ title: "", description: "" }); }); }}>
            <input placeholder="Project name" value={p.title} onChange={(e) => setP({ ...p, title: e.target.value })} required minLength={3} maxLength={150} />
            <textarea placeholder="What it does and what it needs, e.g. 'Replace lead service lines in 12 rural water systems; need $4M for construction.'" rows={3}
              value={p.description} onChange={(e) => setP({ ...p, description: e.target.value })} required minLength={10} maxLength={4000} />
            <button className="btn small">Add project</button>
          </form>

          <h3 className="mini-h">Strategic plan / mandates</h3>
          <ul className="item-list">
            {docs.map((x) => (
              <li key={x.id}>
                <span>{x.title} <span className="muted">({Math.round(x.characters / 1000)}K chars)</span></span>
                <button className="link-btn danger" onClick={() => run(() => api.deleteDocument(agency.id, x.id))}>Remove</button>
              </li>
            ))}
          </ul>
          <form onSubmit={(e) => { e.preventDefault(); run(async () => { await api.addDocument(agency.id, d); setD({ title: "", content: "" }); }); }}>
            <input placeholder="Title, e.g. 2025-2027 Strategic Plan" value={d.title} onChange={(e) => setD({ ...d, title: e.target.value })} required minLength={3} maxLength={200} />
            <textarea placeholder="Paste goals, objectives or statutory mandates…" rows={3} value={d.content}
              onChange={(e) => setD({ ...d, content: e.target.value })} required minLength={50} />
            <div className="row-between">
              <label className="link-btn file-label">
                or upload .txt
                <input type="file" accept=".txt,.md,.csv" onChange={(e) => readFile(e.target.files?.[0])} hidden />
              </label>
              <button className="btn small">Add plan</button>
            </div>
          </form>
        </>
      )}
    </div>
  );
}
