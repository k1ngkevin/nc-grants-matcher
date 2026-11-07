import { useEffect } from "react";

export default function Glossary({ meta, onClose }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const g = meta.glossary;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="gloss-title" onClick={(e) => e.stopPropagation()}>
        <div className="card-head">
          <h2 id="gloss-title">Grant types in plain English</h2>
          <button className="link-btn" onClick={onClose} aria-label="Close">Close ✕</button>
        </div>

        <h3 className="mini-h">How awards are decided</h3>
        <dl className="gloss">
          {Object.entries(g.competition).map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}
        </dl>

        <h3 className="mini-h">Type of funding</h3>
        <dl className="gloss">
          {Object.entries(g.instruments).map(([k, v]) => (<div key={k}><dt>{k}</dt><dd>{v}</dd></div>))}
          <div><dt>Matching funds (cost share)</dt><dd>Your agency must contribute some of the project cost, in cash or in-kind, alongside the federal money.</dd></div>
        </dl>

        <h3 className="mini-h">Deadlines</h3>
        <dl className="gloss">
          {Object.entries(g.timing).map(([k, v]) => (<div key={k}><dt>{v}</dt><dd>{
            { urgent: "Act now. Decide quickly whether to apply.", standard: "Enough time to prepare a strong application.",
              later: "Plenty of runway. Good for planning.", forecasted: "The agency has announced it's coming but it isn't open yet. Start lining up partners and match." }[k]
          }</dd></div>))}
        </dl>

        <h3 className="mini-h">How the match score works</h3>
        <p className="hint">
          Out of 100: fit with your mission and active projects ({meta.weights.semantic}), whether it's a federal program your agency usually receives plus key topics ({meta.weights.program}),
          eligibility ({meta.weights.eligibility}), timing ({meta.weights.timing}) and award size ({meta.weights.size}). Your team's Pursue, Save and Dismiss decisions nudge future scores.
          The score is a recommendation. People make the decisions.
        </p>
        <h3 className="mini-h">Where the data comes from</h3>
        <p className="hint">
          Open opportunities from Grants.gov (refreshed daily), program descriptions from SAM.gov Assistance Listings, and past NC awards from USAspending.gov.
          {" "}Matching uses {meta.ai.embeddings === "azure" ? "Azure OpenAI embeddings" : "local text similarity"}; explanations are {meta.ai.explanations === "rules" ? "rule-based" : "AI-written and grounded in the listing"}.
        </p>
      </div>
    </div>
  );
}
