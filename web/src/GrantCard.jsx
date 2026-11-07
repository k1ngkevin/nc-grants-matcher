import { useEffect, useRef, useState } from "react";
import { fmtDate, money, store } from "./api.js";

const LEVEL_LABEL = { strong: "Strong match", good: "Good match", possible: "Possible match" };
const PART_LABELS = [
  ["semantic", "Fits your mission & projects", "semantic"],
  ["program", "Program you usually receive / key topics", "program"],
  ["eligibility", "Eligibility", "eligibility"],
  ["timing", "Timing", "timing"],
  ["size", "Award size", "size"],
];

function deadlineText(r) {
  const o = r.opportunity, s = r.signals;
  if (s.timing === "forecasted") return o.close_date ? `Forecast · expected due ${fmtDate(o.close_date)}` : "Forecast · not open yet";
  if (s.days_left == null) return "No close date listed";
  if (s.days_left === 0) return "Closes today";
  return `Closes in ${s.days_left} day${s.days_left === 1 ? "" : "s"} · ${fmtDate(o.close_date)}`;
}

export default function GrantCard({ result: r, view, agency, meta, onDecide, startExpanded }) {
  const o = r.opportunity, s = r.signals, g = r.grant_type;
  const [expanded, setExpanded] = useState(!!startExpanded);
  const [panel, setPanel] = useState(null); // "pursue" | "dismiss" | null
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [teamEmail, setTeamEmail] = useState(() => store.get(`team-email:${agency.id}`, ""));
  const [note, setNote] = useState("");
  const ref = useRef(null);

  useEffect(() => {
    if (startExpanded && ref.current) ref.current.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [startExpanded]);

  const act = async (action, extra = {}) => {
    setBusy(true);
    setMsg("");
    try {
      const res = await onDecide(o, action, extra);
      if (action === "pursue" && res?.routed) {
        setMsg(res.routed.delivered ? `Sent to ${extra.route_to}` : `Hand-off email saved to the server outbox (email isn't configured)`);
      }
      setPanel(null);
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  };

  const pursue = () => {
    if (teamEmail) store.set(`team-email:${agency.id}`, teamEmail);
    act("pursue", { route_to: teamEmail.trim(), note });
  };

  return (
    <article ref={ref} className={`grant ${s.timing === "urgent" ? "is-urgent" : ""} ${startExpanded ? "is-focus" : ""}`}>
      <div className="grant-head">
        <div className={`score score-${r.match_level}`} title="Match score out of 100">
          <span className="score-num">{r.score}</span>
          <span className="score-label">{LEVEL_LABEL[r.match_level]}</span>
        </div>
        <div className="grant-title-block">
          <div className="grant-sub">
            {o.federal_agency}
            {o.number && <> · {o.number}</>}
            {o.is_sample ? <span className="tag sample">SAMPLE</span> : null}
          </div>
          <h3 className="grant-title">
            <a href={o.url} target="_blank" rel="noopener noreferrer">{o.title}</a>
          </h3>
          <div className="chips">
            <span className={`chip timing-${s.timing}`}>{deadlineText(r)}</span>
            <span className="chip">{s.amount ? `Up to ${money(s.amount)}` : "Amount not listed"}</span>
            <span className="chip" title={g.competition_help}>{g.competition}</span>
            <span className="chip" title={g.instrument_help}>{g.instrument}</span>
            <span className={`chip ${g.match === "Requires matching funds" ? "chip-warn" : ""}`}>{g.match}</span>
          </div>
        </div>
      </div>

      <div className="why">
        <span className="why-label">Why it fits{r.rationale_source === "ai" ? " (AI summary)" : ""}</span>
        <p>{r.rationale}</p>
        {s.feedback_notes?.length > 0 && <p className="fb-note">Adjusted because {s.feedback_notes.join("; ")}.</p>}
      </div>

      {r.decision && view !== "recommended" && (
        <div className="decision-note">
          {view === "dismiss" && <>Dismissed: {meta.dismiss_reasons[r.decision.reason] || r.decision.reason}. </>}
          {r.decision.note && <>Note: “{r.decision.note}”. </>}
          <span className="muted">{r.decision.created_at?.slice(0, 10)}</span>
        </div>
      )}

      <div className="actions">
        {view !== "pursue" && (
          <button className="btn primary" disabled={busy} onClick={() => setPanel(panel === "pursue" ? null : "pursue")}>Pursue</button>
        )}
        {view !== "save" && view !== "pursue" && (
          <button className="btn" disabled={busy} onClick={() => act("save")}>Save for later</button>
        )}
        {view !== "dismiss" && (
          <button className="btn ghost" disabled={busy} onClick={() => setPanel(panel === "dismiss" ? null : "dismiss")}>Dismiss</button>
        )}
        {view !== "recommended" && (
          <button className="btn ghost" disabled={busy} onClick={() => act("undo")}>Move back to Recommended</button>
        )}
        <button className="link-btn push-right" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
          {expanded ? "Hide details" : "Details & how it was scored"}
        </button>
      </div>

      {panel === "pursue" && (
        <div className="panel">
          <p className="panel-title">Send this to your grant-writing team</p>
          <div className="panel-row">
            <input type="email" placeholder="team@agency.nc.gov (optional)" value={teamEmail} onChange={(e) => setTeamEmail(e.target.value)} />
            <input type="text" placeholder="Note for the team (optional)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
            <button className="btn primary" disabled={busy} onClick={pursue}>Mark as Pursue</button>
          </div>
          <p className="hint">Leave the email blank to just track it under “Pursuing.”</p>
        </div>
      )}

      {panel === "dismiss" && (
        <div className="panel">
          <p className="panel-title">Why isn't this a fit? This improves future rankings for {agency.short}.</p>
          <div className="reason-chips">
            {Object.entries(meta.dismiss_reasons).map(([key, label]) => (
              <button key={key} className="reason" disabled={busy} onClick={() => act("dismiss", { reason: key })}>{label}</button>
            ))}
          </div>
        </div>
      )}

      {msg && <div className="inline-msg">{msg}</div>}

      {expanded && (
        <div className="details">
          <div className="details-grid">
            <div>
              <h4>Score breakdown ({r.score}/100)</h4>
              {PART_LABELS.map(([key, label]) => (
                <div className="bar-row" key={key}>
                  <span className="bar-label">{label}</span>
                  <span className="bar"><span style={{ width: `${(r.breakdown[key] / meta.weights[key]) * 100}%` }} /></span>
                  <span className="bar-val">{r.breakdown[key]}/{meta.weights[key]}</span>
                </div>
              ))}
              {r.breakdown.feedback !== 0 && (
                <div className="bar-row">
                  <span className="bar-label">Your team's past decisions</span>
                  <span className="bar-val wide">{r.breakdown.feedback > 0 ? "+" : ""}{r.breakdown.feedback}</span>
                </div>
              )}
            </div>
            <div>
              <h4>Key facts</h4>
              <dl className="facts">
                <dt>Eligibility</dt><dd>{s.eligibility}</dd>
                <dt>Grant type</dt><dd>{g.competition}: {g.competition_help}</dd>
                {s.matched_project && (<><dt>Your project</dt><dd>{s.matched_project.title}</dd></>)}
                {o.aln_numbers?.length > 0 && (<><dt>Assistance listing</dt><dd>{o.aln_numbers.join(", ")}</dd></>)}
                {o.nc_past_funding ? (<><dt>NC past funding</dt><dd>{money(o.nc_past_funding)} to NC recipients last fiscal year</dd></>) : null}
                {o.estimated_funding ? (<><dt>Total program funding</dt><dd>{money(o.estimated_funding)}{o.expected_awards ? ` across ~${o.expected_awards} awards` : ""}</dd></>) : null}
                <dt>Posted</dt><dd>{fmtDate(o.open_date) || "Not listed"}</dd>
              </dl>
            </div>
          </div>
          {o.description && <p className="desc">{o.description.length > 900 ? o.description.slice(0, 900) + "…" : o.description}</p>}
          <a className="btn ghost small" href={o.url} target="_blank" rel="noopener noreferrer">Open full announcement on {o.source === "sample" ? "Grants.gov (sample link)" : "Grants.gov"} ↗</a>
        </div>
      )}
    </article>
  );
}
