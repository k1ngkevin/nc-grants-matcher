import { useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
import { HandCoins, Info, RefreshCw, RotateCcw, Users, Wrench } from "lucide-react";
import { store } from "./api.js";
import Explained from "./Explained.jsx";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

const FOCUSED_HOURS_PER_WEEK = 30; // a realistic week of application work for one person
const DEFAULT_RATE = 50;           // $/hour, salary plus benefits; each agency sets its own

const dollars = (n) => `$${Math.round(n).toLocaleString("en-US")}`;
const range = (lo, hi, fmt = (x) => x) => (Math.round(lo) === Math.round(hi) ? fmt(lo) : `${fmt(lo)}–${fmt(hi)}`);

/** The state's share for a given federal request. "total" basis: the percent is of the whole project, so the
    federal money is the rest of it. "federal" basis: the percent is of the federal award itself. */
export function matchFor(request, cs) {
  if (!cs?.percent || !request) return null;
  const p = cs.percent / 100;
  const share = cs.basis === "federal" ? request * p : (request * p) / (1 - p);
  return { share, total: request + share };
}

function Source({ source, onCite }) {
  if (!source) return null;
  return (
    <button type="button" onClick={() => onCite(source)}
      className="rounded-sm text-[12.5px] font-medium whitespace-nowrap text-pine-500 underline decoration-pine-300 underline-offset-4 hover:text-pine focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
      p. {source.page}
    </button>
  );
}

/** Effort & match: what the state must put in, how many hours the application takes, and who does them. */
export default function EffortMatch({ data, opportunity: o, agency, onCite, onRerun }) {
  return (
    <div className="grid gap-x-12 gap-y-10 px-5 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="min-w-0">
        {data.effort ? (
          <Effort effort={data.effort} skills={data.special_skills || []} storageKey={`effort:${agency.id}:${o.id}`}
            rateKey={`effort-rate:${agency.id}`} onCite={onCite} />
        ) : (
          <Alert className="border-pine-300 bg-white">
            <Info />
            <AlertTitle>This research was saved before effort estimates existed</AlertTitle>
            <AlertDescription>
              <p>Run the research again to estimate hours, roles and the cost share from the notice.</p>
              <Button size="sm" variant="outline" className="mt-2" onClick={onRerun}><RefreshCw /> Run again</Button>
            </AlertDescription>
          </Alert>
        )}
      </div>
      <aside className="min-w-0">
        <CostShare cs={data.cost_share} opportunity={o} onCite={onCite} />
      </aside>
    </div>
  );
}

function CostShare({ cs, opportunity: o, onCite }) {
  const suggested = o.award_ceiling || o.award_floor || 500_000;
  const [request, setRequest] = useState(String(suggested));
  const amount = Math.max(0, Number(String(request).replace(/[^0-9.]/g, "")) || 0);
  const m = matchFor(amount, cs);
  const listingSaysMatch = o.cost_sharing === 1;

  let body;
  if (cs?.required === false || (!cs?.required && o.cost_sharing === 0 && !cs?.percent)) {
    body = (
      <>
        <p className="font-display text-[34px] leading-none font-extrabold tracking-[-0.03em] text-pine">No match</p>
        <p className="mt-2 text-[14px]">
          {cs?.required === false ? "The notice says no cost share is required." : "The listing says no cost share is required."}{" "}
          <Source source={cs?.source} onCite={onCite} />
        </p>
      </>
    );
  } else if (cs?.percent) {
    body = (
      <>
        <Label htmlFor="request-amount" className="text-[13px] font-normal text-muted-foreground">If you request</Label>
        <div className="mt-1 flex items-center gap-2">
          <span className="font-mono text-muted-foreground">$</span>
          <Input id="request-amount" inputMode="numeric" value={request} onChange={(e) => setRequest(e.target.value)}
            className="h-10 bg-white font-mono text-[15px] tabular-nums" />
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {[["Floor", o.award_floor], ["Ceiling", o.award_ceiling]].filter(([, v]) => v).map(([label, v]) => (
            <Button key={label} size="sm" variant="outline" className="h-7 bg-white text-[12px]" onClick={() => setRequest(String(v))}>
              {label} {dollars(v)}
            </Button>
          ))}
        </div>
        <p className="mt-5 text-[13px] text-muted-foreground">Your agency puts in</p>
        <p className="font-display text-[44px] leading-none font-extrabold tracking-[-0.04em] text-pine tabular-nums">{m ? dollars(m.share) : "$0"}</p>
        <p className="mt-2 text-[14px]">
          A {cs.percent}% match of the {cs.basis === "federal" ? "federal award" : "total project cost"}
          {m && <>, for a total project of <b className="font-extrabold">{dollars(m.total)}</b></>}.{" "}
          <Source source={cs.source} onCite={onCite} />
        </p>
        {cs.basis_assumed && (
          <p className="mt-1 text-[12.5px] text-blaze-deep">The notice didn't say whether the percent is of the federal award or the total project; this assumes the total. Confirm it.</p>
        )}
      </>
    );
  } else {
    body = (
      <>
        <p className="font-display text-[30px] leading-none font-extrabold tracking-[-0.03em] text-blaze-deep">Amount unclear</p>
        <p className="mt-2 text-[14px]">
          {cs?.required || listingSaysMatch
            ? "A match is required, but the notice documents didn't state how much."
            : "Neither the listing nor the notice documents say whether a match is required."}{" "}
          Ask the program officer before you budget. <Source source={cs?.source} onCite={onCite} />
        </p>
      </>
    );
  }

  return (
    <section className="rounded-lg border bg-white p-5" aria-labelledby="cost-share-title">
      <h3 id="cost-share-title" className="mb-4 flex items-center gap-2 text-sm font-extrabold text-pine"><HandCoins className="size-4" /> Cost share</h3>
      {body}
      {cs?.types?.length > 0 && (
        <p className="mt-3 text-[13.5px]">
          Can be {cs.types.map((t) => (t === "in_kind" ? "in-kind (staff time, equipment, space)" : "cash")).join(" or ")}.
        </p>
      )}
      {cs?.detail && <p className="mt-2 text-[13.5px] text-muted-foreground"><Explained text={cs.detail} /></p>}
      {cs?.waiver && <p className="mt-2 border-l-4 border-blaze pl-3 text-[13.5px]"><b className="font-extrabold">Waiver:</b> <Explained text={cs.waiver} /></p>}
      {(cs?.required || cs?.percent || listingSaysMatch) && (
        <p className="mt-4 border-t pt-3 text-[12.5px] text-muted-foreground">
          Plan the match with your budget office before you commit to applying. Check the rule against the notice; AI read it.
        </p>
      )}
    </section>
  );
}

function Effort({ effort, skills, storageKey, rateKey, onCite }) {
  // Per-line edits: { [id]: { low, high, off } }, kept in this browser.
  const [edits, setEdits] = useState(() => store.get(storageKey, {}) || {});
  const [rate, setRate] = useState(() => String(store.get(rateKey, DEFAULT_RATE)));
  useEffect(() => { store.set(storageKey, edits); }, [storageKey, edits]);
  useEffect(() => { const n = Number(rate); if (n > 0) store.set(rateKey, n); }, [rateKey, rate]);

  const lines = useMemo(() => effort.lines.map((l) => {
    const e = edits[l.id] || {};
    return { ...l, low: e.low ?? l.low, high: e.high ?? l.high, off: !!e.off, edited: e.low != null || e.high != null };
  }), [effort.lines, edits]);
  const on = lines.filter((l) => !l.off);
  const low = on.reduce((s, l) => s + l.low, 0);
  const high = on.reduce((s, l) => s + Math.max(l.high, l.low), 0);
  const roles = useMemo(() => {
    const t = {};
    for (const l of on) for (const [role, share] of Object.entries(l.roles)) {
      t[role] = t[role] || [0, 0];
      t[role][0] += l.low * share;
      t[role][1] += Math.max(l.high, l.low) * share;
    }
    return Object.entries(t).map(([role, [lo, hi]]) => ({ role, label: effort.roles[role] || role, lo, hi })).sort((a, b) => b.hi - a.hi);
  }, [on, effort.roles]);
  const maxRole = Math.max(...roles.map((r) => r.hi), 1);
  const hourly = Math.max(0, Number(rate) || 0);
  const edited = Object.keys(edits).length > 0;
  const setLine = (id, patch) => setEdits((e) => ({ ...e, [id]: { ...e[id], ...patch } }));
  const hours = (v) => Math.max(0, Math.min(2000, Math.round(Number(v) || 0)));

  return (
    <div className="flex flex-col gap-10">
      <section>
        <p className="text-[13px] text-muted-foreground">Estimated work to apply</p>
        <p className="mt-1 flex flex-wrap items-baseline gap-x-3">
          <span className="font-display text-[clamp(3rem,7vw,4.5rem)] leading-none font-extrabold tracking-[-0.045em] text-pine tabular-nums">{range(low, high)}</span>
          <span className="display-light text-[28px] leading-none text-pine">hours</span>
        </p>
        <p className="mt-3 max-w-[60ch] text-[15px]">
          About <b className="font-extrabold">{range(low / FOCUSED_HOURS_PER_WEEK, high / FOCUSED_HOURS_PER_WEEK, (x) => x.toFixed(1))} weeks</b> of
          one person's focused time, or <b className="font-extrabold">{range(low * hourly, high * hourly, dollars)}</b> in staff cost.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Label htmlFor="hourly-rate" className="text-[13.5px] font-normal text-muted-foreground">Staff cost per hour</Label>
          <span className="font-mono text-muted-foreground">$</span>
          <Input id="hourly-rate" inputMode="numeric" value={rate} onChange={(e) => setRate(e.target.value.replace(/[^0-9.]/g, ""))}
            className="h-8 w-20 bg-white font-mono tabular-nums" />
          <span className="text-[12.5px] text-muted-foreground">salary plus benefits; set your agency's rate</span>
        </div>
      </section>

      <section aria-labelledby="who-you-need">
        <h3 id="who-you-need" className="mb-3 flex items-center gap-2 text-sm font-extrabold text-pine"><Users className="size-4" /> Who you'll need</h3>
        <dl className="flex flex-col gap-2.5">
          {roles.map((r) => (
            <div key={r.role} className="grid grid-cols-[10rem_minmax(0,1fr)_5.5rem] items-center gap-x-3 sm:grid-cols-[12rem_minmax(0,1fr)_6rem]">
              <dt className="text-[13.5px]">{r.label}</dt>
              <dd><Progress value={(r.hi / maxRole) * 100} className="h-2 bg-pine-100" aria-hidden="true" /></dd>
              <dd className="text-right font-mono text-[12.5px] tabular-nums">{range(r.lo, r.hi, Math.round)} h</dd>
            </div>
          ))}
        </dl>
        {skills.length > 0 && (
          <div className="mt-5 rounded-lg border-l-4 border-blaze bg-blaze-tint/50 px-4 py-3">
            <p className="flex items-center gap-2 text-[13.5px] font-extrabold text-pine-ink"><Wrench className="size-4" /> Specialist skills this notice asks for</p>
            <ul className="mt-2 flex flex-col gap-1.5 text-[13.5px]">
              {skills.map((sk) => (
                <li key={sk.skill}>
                  <b className="font-extrabold">{sk.skill}</b>{sk.why && <span className="text-muted-foreground">: <Explained text={sk.why} /></span>}{" "}
                  <Source source={sk.source} onCite={onCite} />
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[12px] text-muted-foreground">If no one on staff has these, budget time to find a partner or contractor.</p>
          </div>
        )}
      </section>

      <section aria-labelledby="effort-lines">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h3 id="effort-lines" className="text-sm font-extrabold text-pine">What the application needs</h3>
          {edited && <Button size="sm" variant="ghost" className="h-7 text-pine" onClick={() => setEdits({})}><RotateCcw /> Reset to the estimate</Button>}
        </div>
        <ul className="flex flex-col divide-y rounded-lg border bg-white">
          {lines.map((l, i) => (
            <motion.li key={l.id} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.03 * i }}
              className={cn("grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-2 px-4 py-3 sm:grid-cols-[auto_minmax(0,1fr)_auto]", l.off && "opacity-50")}>
              <Checkbox id={`line-${l.id}`} className="mt-1" checked={!l.off} onCheckedChange={(v) => setLine(l.id, { off: !v })}
                aria-label={`Include ${l.label}`} />
              <div className="min-w-0">
                <label htmlFor={`line-${l.id}`} className={cn("text-[14.5px] font-medium", l.off && "line-through")}><Explained text={l.label} /></label>
                <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-muted-foreground">
                  {l.quantity != null && (
                    <span className={cn(l.quantity_assumed && "text-blaze-deep")}>
                      {l.quantity_assumed ? "assumed " : ""}{l.quantity} {l.unit}{l.quantity === 1 ? "" : "s"}
                    </span>
                  )}
                  {l.detail && <span><Explained text={l.detail} /></span>}
                  <Source source={l.source} onCite={onCite} />
                </p>
                <p className="mt-1 flex flex-wrap gap-1">
                  {Object.keys(l.roles).map((r) => (
                    <Badge key={r} variant="secondary" className="rounded-sm bg-muted px-1.5 text-[11px] font-medium text-pine-ink">{effort.roles[r]}</Badge>
                  ))}
                </p>
              </div>
              <div className="col-start-2 flex items-center gap-1.5 sm:col-start-3">
                <Input aria-label={`${l.label}: fewest hours`} inputMode="numeric" value={l.low} disabled={l.off}
                  onChange={(e) => setLine(l.id, { low: hours(e.target.value) })}
                  className={cn("h-8 w-16 bg-white text-right font-mono text-[13px] tabular-nums", l.edited && "border-blaze")} />
                <span className="text-muted-foreground">–</span>
                <Input aria-label={`${l.label}: most hours`} inputMode="numeric" value={l.high} disabled={l.off}
                  onChange={(e) => setLine(l.id, { high: hours(e.target.value) })}
                  className={cn("h-8 w-16 bg-white text-right font-mono text-[13px] tabular-nums", l.edited && "border-blaze")} />
                <span className="text-[12px] text-muted-foreground">h</span>
              </div>
            </motion.li>
          ))}
        </ul>
        <p className="mt-3 max-w-[70ch] text-[12.5px] text-muted-foreground">
          Hours come from a fixed rubric applied to the parts the AI found in the notice (planning figures for an agency that has
          applied for federal grants before). {effort.notes.join(" ")} Untick anything you already have, like a current SAM.gov
          registration, and change any line to match your office. Changes stay in this browser.
        </p>
      </section>
    </div>
  );
}
