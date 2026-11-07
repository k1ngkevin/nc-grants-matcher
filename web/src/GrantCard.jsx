import { useEffect, useRef, useState } from "react";
import { CalendarPlus, ChevronDown, ExternalLink, FileCheck2, FileSearch, Flag, MessageCircleQuestion } from "lucide-react";
import { downloadGrantCalendar, fmtDate, money, store } from "./api.js";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import ResearchDialog from "./ResearchDialog.jsx";
import { AskDialog } from "./AskPanel.jsx";

const LEVEL_LABEL = { strong: "Strong match", good: "Good match", possible: "Possible match" };
// Strong matches invert to solid pine; weaker ones step down in weight, not hue.
const LEVEL_STYLE = {
  strong: "bg-pine text-fog",
  good: "bg-pine-100 text-pine",
  possible: "bg-muted text-muted-foreground",
};
// Eligibility in two words; the full sentence stays in the details.
const ELIGIBILITY_SHORT = [
  [/^State governments/, "States eligible"],
  [/^Public universities/, "Universities eligible"],
  [/^Open to any/, "Anyone can apply"],
  [/Others/, "Check the notice"],
];
const PART_LABELS = [
  ["semantic", "Mission & project text similarity"],
  ["program", "Program alignment & shared topics"],
  ["eligibility", "Eligibility"],
  ["timing", "Timing"],
  ["size", "Award size"],
];

/** Deadline as [label, big value, unit, note]. */
function deadline(r) {
  const o = r.opportunity, s = r.signals;
  if (s.timing === "forecasted") return ["Forecast", "Not open", "", o.close_date ? `Due around ${fmtDate(o.close_date)}` : "No date announced"];
  if (s.days_left == null) return ["Closes", "Rolling", "", "No close date listed"];
  if (s.days_left === 0) return ["Closes", "Today", "", fmtDate(o.close_date)];
  return ["Closes in", String(s.days_left), s.days_left === 1 ? "day" : "days", fmtDate(o.close_date)];
}

function Fact({ label, children, note, className }) {
  return (
    <div className={cn("min-w-0", className)}>
      <dt className="text-[12px] text-muted-foreground">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
      {note && <dd className="mt-0.5 text-[12.5px] text-muted-foreground">{note}</dd>}
    </div>
  );
}

/** The four things that decide whether to look closer: time left, money, cost share, eligibility. */
function KeyFacts({ r, className }) {
  const o = r.opportunity, s = r.signals, g = r.grant_type;
  const [dLabel, dValue, dUnit, dNote] = deadline(r);
  const numeric = /^\d/.test(dValue);
  const urgent = s.timing === "urgent";
  const elig = ELIGIBILITY_SHORT.find(([re]) => re.test(s.eligibility || ""))?.[1] || "Check the notice";
  const match = g.match === "Requires matching funds" ? "Required" : g.match === "No match required" ? "None" : "Not stated";
  const big = "font-display text-[28px] leading-none font-extrabold tracking-[-0.03em] tabular-nums md:text-[32px]";
  return (
    <dl className={className}>
      <Fact label={dLabel} note={dNote}>
        <span className={cn(numeric ? big : "text-[17px] leading-tight font-extrabold", urgent ? "text-urgent" : "text-pine")}>{dValue}</span>
        {dUnit && <span className={cn("ml-1 text-[14px] font-medium", urgent ? "text-urgent" : "text-pine")}>{dUnit}</span>}
      </Fact>
      <Fact label={s.amount && o.award_ceiling ? "Up to" : "Award"}
        note={o.expected_awards ? `About ${o.expected_awards} award${o.expected_awards === 1 ? "" : "s"}` : null}>
        {s.amount
          ? <span className={cn(big, "text-pine")}>{money(s.amount)}</span>
          : <span className="text-[17px] leading-tight font-extrabold text-muted-foreground">Not listed</span>}
      </Fact>
      <Fact label="Cost share">
        <span className={cn("text-[15px] font-extrabold", match === "Required" ? "text-pine-ink underline decoration-blaze decoration-2 underline-offset-4" : "text-pine")}>{match}</span>
      </Fact>
      <Fact label="Eligibility">
        <span className={cn("text-[15px] font-extrabold", elig === "Check the notice" ? "text-blaze-deep" : "text-pine")}>{elig}</span>
      </Fact>
    </dl>
  );
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

export default function GrantCard({ result: r, view, agency, meta, onDecide, startExpanded, onFeedback }) {
  const o = r.opportunity, s = r.signals, g = r.grant_type;
  const [expanded, setExpanded] = useState(!!startExpanded);
  const [panel, setPanel] = useState(null); // "pursue" | "dismiss" | null
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [teamEmail, setTeamEmail] = useState(() => store.get(`team-email:${agency.id}`, ""));
  const [note, setNote] = useState("");
  const [researchOpen, setResearchOpen] = useState(false);
  const [researchMounted, setResearchMounted] = useState(false); // keep results after the first open
  const ref = useRef(null);
  const canResearch = meta.ai?.research;
  // When this agency last saved research on the grant. Set from search results, and as soon as a run finishes.
  const [researchAt, setResearchAt] = useState(r.research_at || null);
  useEffect(() => { if (r.research_at) setResearchAt(r.research_at); }, [r.research_at]);
  const openResearch = () => { setResearchMounted(true); setResearchOpen(true); };
  const [askOpen, setAskOpen] = useState(false);
  const [askMounted, setAskMounted] = useState(false); // keep the conversation while the card is on screen
  const openAsk = () => { setAskMounted(true); setAskOpen(true); };

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
      // Phone: score | title, facts strip, body.  Desktop: score | title + body | facts rail.
      "grid gap-0 overflow-hidden py-0 grid-cols-[72px_minmax(0,1fr)] sm:grid-cols-[96px_minmax(0,1fr)] md:grid-cols-[96px_minmax(0,1fr)_200px] md:grid-rows-[auto_1fr]",
      "[grid-template-areas:'score_head''score_facts''score_body'] md:[grid-template-areas:'score_head_facts''score_body_facts']",
      s.timing === "urgent" && "border-l-4 border-l-urgent",
      startExpanded && "ring-2 ring-ring",
    )}>
      <div className={cn("flex flex-col items-center px-1 pt-5 pb-4 text-center [grid-area:score]", LEVEL_STYLE[r.match_level])}
        title="Ranking score out of 100. Match labels also require mission and program relevance.">
        <span className="font-display text-[44px] leading-none font-extrabold tracking-[-0.04em] tabular-nums sm:text-[52px]">{r.score}</span>
        <span className="mt-2 text-[11.5px] leading-tight font-medium">{LEVEL_LABEL[r.match_level]}</span>
      </div>

      <div className="min-w-0 px-4 pt-4 sm:px-6 sm:pt-6 [grid-area:head]">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted-foreground">
            <span>{o.federal_agency}</span>
            {o.number && <span className="font-mono text-[12px] tabular-nums">{o.number}</span>}
            {o.is_sample ? <Badge className="bg-blaze-tint text-[11px] text-blaze-deep">Sample</Badge> : null}
            {researchAt && <Badge className="gap-1 bg-pine-100 text-[11px] text-pine"><FileCheck2 className="size-3" /> Researched</Badge>}
          </div>
          <h3 className="mt-1 mb-3 text-[19px] leading-snug font-extrabold tracking-[-0.01em]">
            <a href={o.url} target="_blank" rel="noopener noreferrer" className="text-pine decoration-blaze decoration-2 underline-offset-4 hover:underline">{o.title}</a>
          </h3>
          <div className="flex flex-wrap gap-1.5">
            <Chip help={g.competition_help}>{g.competition}</Chip>
            <Chip help={g.instrument_help}>{g.instrument}</Chip>
          </div>
      </div>

      <KeyFacts r={r} className={cn(
        "mx-4 mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-y py-3 sm:mx-6 [grid-area:facts]",
        "md:m-0 md:flex md:flex-col md:gap-5 md:border-y-0 md:border-l md:bg-fog/60 md:px-5 md:py-6",
      )} />

      <div className="min-w-0 px-4 pt-4 pb-4 sm:px-6 sm:pb-6 [grid-area:body]">
          <div className="max-w-[75ch]">
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
            <p className={cn("mt-1 text-[15.5px] leading-relaxed", !expanded && "line-clamp-3")}>{withBold(r.rationale)}</p>
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
              {researchAt ? (
                // Saved research opens without a new AI run, so it works even when AI isn't configured.
                <Button size="sm" className="font-extrabold" onClick={openResearch}>
                  <FileCheck2 /> View research
                  <span className="font-extralight text-pine-100">{fmtDate(researchAt.slice(0, 10))}</span>
                </Button>
              ) : canResearch ? (
                <Button size="sm" variant="outline" className="border-pine-300 text-pine" onClick={openResearch}>
                  <FileSearch /> Research this grant
                </Button>
              ) : (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span tabIndex={0} className="rounded-md"><Button size="sm" variant="outline" disabled><FileSearch /> Research this grant</Button></span>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">Reads the notice PDFs with AI. Needs Azure OpenAI chat to be set up on the server.</TooltipContent>
                </Tooltip>
              )}
              {canResearch && (
                <Button size="sm" variant="outline" className="border-pine-300 text-pine" onClick={openAsk}>
                  <MessageCircleQuestion /> Ask about this grant
                </Button>
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
                      {!!r.breakdown.award_type && (
                        <div className="flex justify-between gap-3 text-[13px]">
                          <span>{r.breakdown.award_type > 0 ? "Formula / mandatory funding" : "Continuation (usually current grantees only)"}</span>
                          <span className={cn("font-mono text-[12px] tabular-nums", r.breakdown.award_type > 0 ? "text-pine" : "text-urgent")}>
                            {r.breakdown.award_type > 0 ? "+" : ""}{r.breakdown.award_type}
                          </span>
                        </div>
                      )}
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
                <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
                <Button asChild variant="outline" size="sm">
                  <a href={o.url} target="_blank" rel="noopener noreferrer">
                    Open full announcement on {o.source === "sample" ? "Grants.gov (sample link)" : "Grants.gov"} <ExternalLink />
                  </a>
                </Button>
                  {o.close_date && (
                    <Button variant="link" size="sm" className="h-auto p-0 text-pine" disabled={busy}
                      onClick={() => downloadGrantCalendar(agency.id, o.id).catch((e) => setMsg(e.message))}>
                      <CalendarPlus /> Add {researchAt ? "deadline and research timeline" : "deadline"} to my calendar
                    </Button>
                  )}
                  {onFeedback && (
                    <Button variant="link" size="sm" className="h-auto p-0 text-muted-foreground hover:text-pine" onClick={onFeedback}>
                      <Flag /> Report a problem with this grant
                    </Button>
                  )}
                </div>
              </div>
            </CollapsibleContent>
          </Collapsible>
      </div>
    </Card>
    {askMounted && <AskDialog open={askOpen} onOpenChange={setAskOpen} opportunity={o} agency={agency} />}
    {researchMounted && <ResearchDialog open={researchOpen} onOpenChange={setResearchOpen} result={r} agency={agency} onDone={setResearchAt} />}
    </div>
  );
}
