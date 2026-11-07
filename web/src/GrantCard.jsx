import { useEffect, useRef, useState } from "react";
import { ChevronDown, ExternalLink } from "lucide-react";
import { fmtDate, money, store } from "./api.js";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const LEVEL_LABEL = { strong: "Strong match", good: "Good match", possible: "Possible match" };
// Strong matches invert to solid pine; weaker ones step down in weight, not hue.
const LEVEL_STYLE = {
  strong: "bg-pine text-fog",
  good: "bg-pine-100 text-pine",
  possible: "bg-muted text-muted-foreground",
};
// Color only where it means something: red for closing soon, a dashed outline for "not open yet".
const TIMING_STYLE = {
  urgent: "bg-urgent text-white font-extrabold",
  standard: "bg-pine-100 text-pine",
  later: "",
  forecasted: "border-dashed border-pine-500 bg-transparent text-pine",
};
const PART_LABELS = [
  ["semantic", "Mission & project text similarity"],
  ["program", "Program alignment & shared topics"],
  ["eligibility", "Eligibility"],
  ["timing", "Timing"],
  ["size", "Award size"],
];

function deadlineText(r) {
  const o = r.opportunity, s = r.signals;
  if (s.timing === "forecasted") return o.close_date ? `Forecast, expected due ${fmtDate(o.close_date)}` : "Forecast, not open yet";
  if (s.days_left == null) return "No close date listed";
  if (s.days_left === 0) return "Closes today";
  return `Closes in ${s.days_left} day${s.days_left === 1 ? "" : "s"} (${fmtDate(o.close_date)})`;
}

// AI rationales sometimes use **markdown bold**; show it as bold rather than asterisks.
function withBold(text) {
  return (text || "").split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? <strong key={i}>{part}</strong> : part));
}

function Chip({ className, help, children }) {
  const badge = <Badge variant="secondary" className={cn("rounded-sm border-transparent bg-muted px-2 py-0.5 text-[12.5px] font-medium text-pine-ink", className)} tabIndex={help ? 0 : undefined}>{children}</Badge>;
  if (!help) return badge;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{badge}</TooltipTrigger>
      <TooltipContent className="max-w-xs">{help}</TooltipContent>
    </Tooltip>
  );
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
        setMsg(res.routed.delivered ? `Sent to ${extra.route_to}`
          : res.routed.error ? `Marked Pursue, but the email to ${extra.route_to} couldn't be sent. Forward it yourself or try again later.`
          : `Hand-off email saved to the server outbox (email isn't configured)`);
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
    <div ref={ref}>
    <Card className={cn(
      "flex-row gap-0 overflow-hidden py-0",
      s.timing === "urgent" && "border-l-4 border-l-urgent",
      startExpanded && "ring-2 ring-ring",
    )}>
      <div className={cn("flex w-[76px] shrink-0 flex-col items-center px-1 pt-5 pb-4 text-center sm:w-[96px]", LEVEL_STYLE[r.match_level])}
        title="Ranking score out of 100. Match labels also require mission and program relevance.">
        <span className="font-display text-[44px] leading-none font-extrabold tracking-[-0.04em] tabular-nums sm:text-[52px]">{r.score}</span>
        <span className="mt-2 text-[11.5px] leading-tight font-medium">{LEVEL_LABEL[r.match_level]}</span>
      </div>

      <div className="min-w-0 flex-1 p-4 sm:p-6">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted-foreground">
            <span>{o.federal_agency}</span>
            {o.number && <span className="font-mono text-[12px] tabular-nums">{o.number}</span>}
            {o.is_sample ? <Badge className="bg-blaze-tint text-[11px] text-blaze-deep">Sample</Badge> : null}
          </div>
          <h3 className="mt-1 mb-3 text-[19px] leading-snug font-extrabold tracking-[-0.01em]">
            <a href={o.url} target="_blank" rel="noopener noreferrer" className="text-pine decoration-blaze decoration-2 underline-offset-4 hover:underline">{o.title}</a>
          </h3>
          <div className="flex flex-wrap gap-1.5">
            <Chip className={TIMING_STYLE[s.timing]}>{deadlineText(r)}</Chip>
            <Chip>{s.amount ? `Up to ${money(s.amount)}` : "Amount not listed"}</Chip>
            <Chip help={g.competition_help}>{g.competition}</Chip>
            <Chip help={g.instrument_help}>{g.instrument}</Chip>
            <Chip className={g.match === "Requires matching funds" ? "border-pine-ink bg-transparent font-extrabold" : ""}>{g.match}</Chip>
          </div>

          <div className="mt-4 max-w-[75ch]">
            {r.score_preview && (
              <dl className="mb-4 grid gap-x-6 gap-y-3 text-[13px] sm:grid-cols-2">
                {[
                  ["Mission & program relevance", r.score_preview.relevance_points, r.score_preview.relevance_max],
                  ["Eligibility, timing & award size", r.score_preview.practical_points, r.score_preview.practical_max],
                ].map(([label, pts, max]) => (
                  <div key={label}>
                    <div className="flex items-baseline justify-between gap-2">
                      <dt className="text-muted-foreground">{label}</dt>
                      <dd className="font-mono text-[12px] tabular-nums">{pts}/{max}</dd>
                    </div>
                    <Progress value={(pts / max) * 100} className="mt-1.5 h-1 bg-muted" aria-label={label} />
                  </div>
                ))}
              </dl>
            )}
            {r.score_preview?.caution && <p className="mb-2 text-[13px] font-extrabold text-blaze-deep">{r.score_preview.caution}</p>}
            <p className="text-[13px] text-muted-foreground">{r.rationale_source === "ai" ? "AI summary" : "Why it matches"}</p>
            <p className="mt-1 text-[15.5px] leading-relaxed">{withBold(r.rationale)}</p>
            {s.feedback_notes?.length > 0 && <p className="mt-1 text-[13px] text-muted-foreground italic">Adjusted because {s.feedback_notes.join("; ")}.</p>}
          </div>

          {r.decision && view !== "recommended" && (
            <p className="mt-2 text-[13.5px]">
              {view === "dismiss" && <>Dismissed: {meta.dismiss_reasons[r.decision.reason] || r.decision.reason}. </>}
              {r.decision.note && <>Note: “{r.decision.note}”. </>}
              <span className="text-muted-foreground">{r.decision.created_at?.slice(0, 10)}</span>
            </p>
          )}

          <Collapsible open={expanded} onOpenChange={setExpanded}>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              {view !== "pursue" && (
                <Button size="sm" variant="blaze" className="px-4" disabled={busy} onClick={() => setPanel(panel === "pursue" ? null : "pursue")} aria-expanded={panel === "pursue"}>Pursue</Button>
              )}
              {view !== "save" && view !== "pursue" && (
                <Button size="sm" variant="outline" disabled={busy} onClick={() => act("save")}>Save for later</Button>
              )}
              {view !== "dismiss" && (
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => setPanel(panel === "dismiss" ? null : "dismiss")} aria-expanded={panel === "dismiss"}>Dismiss</Button>
              )}
              {view !== "recommended" && (
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => act("undo")}>Move back to Recommended</Button>
              )}
              <CollapsibleTrigger asChild>
                <Button size="sm" variant="link" className="px-0 sm:ml-auto">
                  {expanded ? "Hide details" : "Details & how it was scored"}
                  <ChevronDown className={cn("transition-transform motion-reduce:transition-none", expanded && "rotate-180")} />
                </Button>
              </CollapsibleTrigger>
            </div>

            {panel === "pursue" && (
              <div className="mt-3 rounded-lg border bg-muted/50 p-3">
                <p className="mb-2 text-sm font-extrabold">Send this to your grant-writing team</p>
                <div className="flex flex-col gap-2 md:flex-row">
                  <Input type="email" className="bg-white" placeholder="team@agency.nc.gov (optional)" value={teamEmail} onChange={(e) => setTeamEmail(e.target.value)} aria-label="Team email" />
                  <Input className="bg-white" placeholder="Note for the team (optional)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} aria-label="Note for the team" />
                  <Button variant="blaze" disabled={busy} onClick={pursue}>Mark as Pursue</Button>
                </div>
                <p className="mt-2 text-[13px] text-muted-foreground">Leave the email blank to just track it under Pursuing.</p>
              </div>
            )}

            {panel === "dismiss" && (
              <div className="mt-3 rounded-lg border bg-muted/50 p-3">
                <p className="mb-2 text-sm font-extrabold">Why isn't this a fit? Your answer improves future rankings for {agency.short}.</p>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(meta.dismiss_reasons).map(([key, label]) => (
                    <Button key={key} size="sm" variant="outline" className="rounded-full bg-white hover:border-urgent/40 hover:bg-urgent-bg hover:text-urgent"
                      disabled={busy} onClick={() => act("dismiss", { reason: key })}>{label}</Button>
                  ))}
                </div>
              </div>
            )}

            {msg && <p className="mt-2 text-[13.5px] font-medium text-pine" role="status">{msg}</p>}

            <CollapsibleContent>
              <div className="mt-4 border-t pt-4">
                <div className="grid gap-6 md:grid-cols-2">
                  <div>
                    <h4 className="mb-1 text-sm font-extrabold">Ranking score breakdown ({r.score}/100)</h4>
                    <p className="mb-3 text-[13px] text-muted-foreground">Use these signals to prioritize review and confirm that the funded activities fit your agency.</p>
                    <div className="flex flex-col gap-2.5">
                      {PART_LABELS.map(([key, label]) => (
                        <div key={key} className="grid grid-cols-[1fr_44px] items-center gap-x-3 gap-y-1 text-[13px]">
                          <span>{label}</span>
                          <span className="text-right font-mono text-[12px] text-muted-foreground tabular-nums">{r.breakdown[key]}/{meta.weights[key]}</span>
                          <Progress value={(r.breakdown[key] / meta.weights[key]) * 100} className="col-span-2 h-1.5 bg-muted" aria-label={label} />
                        </div>
                      ))}
                      {r.breakdown.feedback !== 0 && (
                        <div className="flex justify-between text-[13px]">
                          <span>Your team's past decisions</span>
                          <span className="text-muted-foreground tabular-nums">{r.breakdown.feedback > 0 ? "+" : ""}{r.breakdown.feedback}</span>
                        </div>
                      )}
                    </div>
                  </div>
                  <div>
                    <h4 className="mb-3 text-sm font-extrabold">Key facts</h4>
                    <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-1.5 text-[13.5px]">
                      <dt className="text-muted-foreground">Eligibility</dt><dd>{s.eligibility}</dd>
                      <dt className="text-muted-foreground">Grant type</dt><dd>{g.competition}: {g.competition_help}</dd>
                      {s.matched_project && (<><dt className="text-muted-foreground">Your project</dt><dd>{s.matched_project.title}</dd></>)}
                      {o.aln_numbers?.length > 0 && (<><dt className="text-muted-foreground">Assistance listing</dt><dd className="font-mono text-[12.5px]">{o.aln_numbers.join(", ")}</dd></>)}
                      {o.nc_past_funding ? (<><dt className="text-muted-foreground">NC past funding</dt><dd>{money(o.nc_past_funding)} to NC recipients last fiscal year</dd></>) : null}
                      {o.estimated_funding ? (<><dt className="text-muted-foreground">Total program funding</dt><dd>{money(o.estimated_funding)}{o.expected_awards ? ` across ~${o.expected_awards} awards` : ""}</dd></>) : null}
                      <dt className="text-muted-foreground">Posted</dt><dd>{fmtDate(o.open_date) || "Not listed"}</dd>
                    </dl>
                  </div>
                </div>
                {o.description && (
                  <p className="mt-4 max-w-[75ch] text-sm text-foreground/85">{o.description.length > 900 ? o.description.slice(0, 900) + "…" : o.description}</p>
                )}
                <Button asChild variant="outline" size="sm" className="mt-4">
                  <a href={o.url} target="_blank" rel="noopener noreferrer">
                    Open full announcement on {o.source === "sample" ? "Grants.gov (sample link)" : "Grants.gov"} <ExternalLink />
                  </a>
                </Button>
              </div>
            </CollapsibleContent>
          </Collapsible>
      </div>
    </Card>
    </div>
  );
}
