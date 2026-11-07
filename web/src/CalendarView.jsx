import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
import {
  AlertTriangle,
  CalendarClock,
  CalendarPlus,
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  Flag,
  ListChecks,
  Loader2,
  Telescope,
} from "lucide-react";
import { api, documentUrl, downloadGrantCalendar, saveFile, store } from "./api.js";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

const RECOMMENDED_LIMIT = 15;
const LAYERS = [
  ["pursue", "Pursuing"],
  ["save", "Saved"],
  ["recommended", `Top ${RECOMMENDED_LIMIT} recommended`],
  ["research", "Research timelines"],
];
const DEFAULT_LAYERS = ["pursue", "save", "research"];
const KIND = {
  deadline: { label: "Applications due", icon: Flag },
  forecast: { label: "Expected due date (forecast)", icon: Telescope },
  key_date: { label: "Key date from the notice", icon: CalendarClock },
  step: { label: "Suggested step", icon: ListChecks },
};
const STATUS = { pursue: "Pursuing", save: "Saved", recommended: "Recommended" };
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MAX_CHIPS = 3;

// ---- dates (all local, all-day) ----
const parse = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };
const iso = (dt) => `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
const todayIso = () => iso(new Date());
const daysBetween = (a, b) => Math.round((parse(b) - parse(a)) / 86_400_000);

function relative(dateIso) {
  const n = daysBetween(todayIso(), dateIso);
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  if (n === -1) return "yesterday";
  return n > 0 ? `in ${n} days` : `${-n} days ago`;
}

function longDate(dateIso) {
  return parse(dateIso).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

/** Weeks (Sunday first) covering the month. */
function monthGrid(year, month) {
  const first = new Date(year, month, 1);
  const start = new Date(year, month, 1 - first.getDay());
  const last = new Date(year, month + 1, 0);
  const days = Math.ceil((first.getDay() + last.getDate()) / 7) * 7;
  return Array.from({ length: days }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
}

/** A deadline within 14 days is the one red thing on the page, as on the grant cards. */
function isUrgent(e) {
  if (e.kind !== "deadline") return false;
  const n = daysBetween(todayIso(), e.date);
  return n >= 0 && n <= 14;
}

function chipClass(e) {
  const past = e.date < todayIso();
  return cn(
    "flex w-full min-w-0 items-center gap-1 rounded-sm px-1.5 py-0.5 text-left text-[12px] leading-tight font-medium",
    "focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
    e.kind === "deadline" && (isUrgent(e) ? "bg-urgent text-white" : "bg-pine text-fog"),
    e.kind === "forecast" && "border border-dashed border-pine-500 bg-white text-pine",
    e.kind === "key_date" && "bg-pine-100 text-pine-ink",
    e.kind === "step" && "bg-blaze-tint text-pine-ink shadow-[inset_3px_0_0_var(--blaze)]",
    past && "opacity-55",
  );
}

const chipText = (e) => (e.kind === "deadline" || e.kind === "forecast" ? e.opportunity.title : e.title);

/** Deadlines for the grants an agency tracks and the dated steps from saved research, by month or as a list. */
export default function CalendarView({ agency, filters, onOpenGrant }) {
  const [layers, setLayers] = useState(() => {
    const saved = store.get("calendar-layers");
    return Array.isArray(saved) ? saved.filter((l) => LAYERS.some(([k]) => k === l)) : DEFAULT_LAYERS;
  });
  const [mode, setMode] = useState(() => (window.matchMedia?.("(min-width: 768px)").matches ? "month" : "list"));
  const [cursor, setCursor] = useState(() => { const t = new Date(); return { y: t.getFullYear(), m: t.getMonth() }; });
  const [state, setState] = useState({ status: "loading" });
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");

  useEffect(() => { store.set("calendar-layers", layers); }, [layers]);

  const body = useMemo(() => ({
    agency_id: agency.id,
    include: layers,
    filters,
    recommended_limit: RECOMMENDED_LIMIT,
  }), [agency.id, layers, filters]);

  useEffect(() => {
    let live = true;
    setState((s) => ({ status: "loading", data: s.data }));
    api.calendar(body)
      .then((data) => live && setState({ status: "done", data }))
      .catch((e) => live && setState({ status: "error", error: e.message }));
    return () => { live = false; };
  }, [body]);

  const data = state.data;
  const events = data?.events || [];
  const byDate = useMemo(() => {
    const m = new Map();
    for (const e of events) m.set(e.date, [...(m.get(e.date) || []), e]);
    return m;
  }, [events]);

  const toggle = (key, on) => setLayers((ls) => (on ? [...new Set([...ls, key])] : ls.filter((l) => l !== key)));
  const shift = (n) => setCursor(({ y, m }) => { const d = new Date(y, m + n, 1); return { y: d.getFullYear(), m: d.getMonth() }; });
  const goToday = () => { const t = new Date(); setCursor({ y: t.getFullYear(), m: t.getMonth() }); };

  const exportIcs = async () => {
    setExporting(true);
    setExportError("");
    try {
      saveFile(await api.calendarIcs(body), `grant-calendar-${agency.id}.ics`);
    } catch (e) {
      setExportError(e.message);
    } finally {
      setExporting(false);
    }
  };

  const upcoming = events.filter((e) => e.date >= todayIso()).length;
  const nextEvent = events.find((e) => e.date >= todayIso());
  const monthLabel = new Date(cursor.y, cursor.m, 1).toLocaleDateString("en-US", { month: "long" });

  return (
    <section aria-label="Grant calendar" className="flex flex-col gap-5">
      <Card className="gap-4 bg-white px-4 py-4 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
          <fieldset className="min-w-0">
            <legend className="mb-2 text-[13px] text-muted-foreground">Show on the calendar</legend>
            <div className="flex flex-wrap gap-x-5 gap-y-2">
              {LAYERS.map(([key, label]) => (
                <div key={key} className="flex items-center gap-2">
                  <Checkbox id={`layer-${key}`} checked={layers.includes(key)} onCheckedChange={(on) => toggle(key, !!on)} />
                  <Label htmlFor={`layer-${key}`} className="text-[14px] font-medium">{label}</Label>
                </div>
              ))}
            </div>
          </fieldset>
          <div className="flex flex-wrap items-center gap-2">
            <Tabs value={mode} onValueChange={setMode}>
              <TabsList className="h-9">
                <TabsTrigger value="month" className="px-3">Month</TabsTrigger>
                <TabsTrigger value="list" className="px-3">List</TabsTrigger>
              </TabsList>
            </Tabs>
            <Button variant="blaze" onClick={exportIcs} disabled={exporting || !events.length}>
              {exporting ? <Loader2 className="animate-spin" /> : <Download />} Add to my calendar (.ics)
            </Button>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-t pt-3">
          <Legend />
          <p className="text-[12.5px] text-muted-foreground">
            The .ics file opens in Outlook, Google Calendar or Apple Calendar, with reminders two weeks and three days before each deadline.
          </p>
        </div>
        {exportError && <p className="text-[13px] font-medium text-urgent" role="alert">{exportError}</p>}
      </Card>

      {state.status === "error" && (
        <Alert variant="destructive" className="bg-urgent-bg">
          <AlertTriangle />
          <AlertTitle>Couldn't load the calendar</AlertTitle>
          <AlertDescription>{state.error}</AlertDescription>
        </Alert>
      )}
      {state.status === "loading" && !data && <Skeleton className="h-[560px] rounded-lg bg-white" />}

      {data && (
        <div className={cn("transition-opacity motion-reduce:transition-none", state.status === "loading" && "opacity-55")}>
          <div className="mb-4 flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
            {mode === "month" ? (
              <h2 className="flex items-baseline gap-3 text-pine">
                <span className="display-light text-[clamp(2.4rem,5vw,3.75rem)] leading-none tracking-[-0.03em]">{monthLabel}</span>
                <span className="font-display text-[clamp(1.4rem,2.6vw,2rem)] leading-none font-extrabold tabular-nums">{cursor.y}</span>
              </h2>
            ) : (
              <h2 className="display-light text-[clamp(2.4rem,5vw,3.75rem)] leading-none tracking-[-0.03em] text-pine">Coming up</h2>
            )}
            <div className="flex items-center gap-3">
              <p className="text-[13.5px] text-muted-foreground" aria-live="polite">
                <strong className="font-extrabold text-pine">{upcoming}</strong> upcoming date{upcoming === 1 ? "" : "s"} across {data.grant_count} grant{data.grant_count === 1 ? "" : "s"}
              </p>
              {mode === "month" && (
                <div className="flex items-center gap-1">
                  <Button variant="outline" size="icon" className="bg-white" onClick={() => shift(-1)} aria-label="Previous month"><ChevronLeft /></Button>
                  <Button variant="outline" size="sm" className="bg-white" onClick={goToday}>Today</Button>
                  <Button variant="outline" size="icon" className="bg-white" onClick={() => shift(1)} aria-label="Next month"><ChevronRight /></Button>
                </div>
              )}
            </div>
          </div>

          {!events.length ? (
            <EmptyCalendar layers={layers} />
          ) : mode === "month" ? (
            <MonthGrid key={`${cursor.y}-${cursor.m}`} cursor={cursor} byDate={byDate} agency={agency} onOpenGrant={onOpenGrant}
              nextEvent={nextEvent} onJump={(e) => { const d = parse(e.date); setCursor({ y: d.getFullYear(), m: d.getMonth() }); }} />
          ) : (
            <AgendaList events={events} agency={agency} onOpenGrant={onOpenGrant} />
          )}

          {data.undated_steps > 0 && layers.includes("research") && (
            <p className="mt-3 text-[13px] text-muted-foreground">
              {data.undated_steps} research step{data.undated_steps === 1 ? " has" : "s have"} no date, so {data.undated_steps === 1 ? "it isn't" : "they aren't"} on the calendar. Open the grant's research to see {data.undated_steps === 1 ? "it" : "them"}.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function Legend() {
  const sample = (kind, urgent) => ({ kind: urgent ? "deadline" : kind, date: urgent ? todayIso() : "9999-12-31", title: "", opportunity: { title: "" } });
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-[12.5px] text-muted-foreground" aria-label="Key">
      {[["deadline", "Due"], ["deadline", "Due within 14 days", true], ["forecast", "Forecast due date"], ["key_date", "Date in the notice"], ["step", "Suggested step"]].map(([kind, label, urgent]) => {
        const Icon = KIND[kind].icon;
        return (
          <li key={label} className="flex items-center gap-1.5">
            <span className={cn(chipClass(sample(kind, urgent)), "w-auto px-1 py-0.5")} aria-hidden="true"><Icon className="size-3" /></span>
            {label}
          </li>
        );
      })}
    </ul>
  );
}

function EmptyCalendar({ layers }) {
  return (
    <Card className="items-center gap-2 border-dashed bg-white/60 py-14 text-center">
      <p className="display-light text-3xl text-pine">Nothing on the calendar yet</p>
      <p className="max-w-md text-sm text-muted-foreground">
        {layers.length === 0
          ? "Turn on at least one layer above."
          : "Mark grants as Pursue or Save for later, or turn on Top recommended. Researching a grant adds its suggested timeline."}
      </p>
    </Card>
  );
}

function MonthGrid({ cursor, byDate, agency, onOpenGrant, nextEvent, onJump }) {
  const days = monthGrid(cursor.y, cursor.m);
  const today = todayIso();
  const inMonth = days.some((d) => d.getMonth() === cursor.m && byDate.has(iso(d)));
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease: [0.2, 0.7, 0.2, 1] }}>
      <div className="overflow-hidden rounded-lg border bg-border">
        <div className="grid grid-cols-7 gap-px" aria-hidden="true">
          {WEEKDAYS.map((w) => (
            <div key={w} className="bg-fog px-2 py-1.5 font-mono text-[11px] tracking-wide text-muted-foreground uppercase">{w}</div>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-px border-t">
          {days.map((d) => {
            const key = iso(d);
            const list = byDate.get(key) || [];
            const out = d.getMonth() !== cursor.m;
            const isToday = key === today;
            const extra = list.length - MAX_CHIPS;
            return (
              <div key={key}
                className={cn("flex min-h-[112px] min-w-0 flex-col gap-1 p-1 sm:p-1.5", out ? "bg-fog/70" : "bg-white")}>
                {list.length > 0 && <span className="sr-only">{longDate(key)}</span>}
                <span aria-hidden="true" className={cn("grid size-6 place-items-center rounded-full font-mono text-[12px] tabular-nums",
                  isToday ? "bg-blaze font-extrabold text-pine-ink" : out ? "text-muted-foreground/60" : "text-muted-foreground")}>
                  {d.getDate()}
                </span>
                {list.slice(0, MAX_CHIPS).map((e) => (
                  <EventPopover key={e.id} event={e} agency={agency} onOpenGrant={onOpenGrant}>
                    <button type="button" className={chipClass(e)} title={chipText(e)}>
                      <ChipIcon kind={e.kind} />
                      <span className="hidden truncate sm:inline">{chipText(e)}</span>
                    </button>
                  </EventPopover>
                ))}
                {extra > 0 && (
                  <Popover>
                    <PopoverTrigger asChild>
                      <button type="button" className="rounded-sm px-1.5 text-left text-[12px] font-extrabold text-pine hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
                        +{extra} more
                      </button>
                    </PopoverTrigger>
                    <PopoverContent className="max-h-[70vh] w-80 overflow-y-auto p-0">
                      <p className="border-b px-4 py-2.5 text-[13px] font-extrabold text-pine">{longDate(key)}</p>
                      <div className="divide-y">
                        {list.map((e) => <div key={e.id} className="px-4 py-3"><EventDetail event={e} agency={agency} onOpenGrant={onOpenGrant} /></div>)}
                      </div>
                    </PopoverContent>
                  </Popover>
                )}
              </div>
            );
          })}
        </div>
      </div>
      {!inMonth && nextEvent && (
        <p className="mt-3 text-[13.5px] text-muted-foreground">
          Nothing this month.{" "}
          <Button variant="link" className="h-auto p-0 text-[13.5px]" onClick={() => onJump(nextEvent)}>
            Jump to the next date ({longDate(nextEvent.date)})
          </Button>
        </p>
      )}
    </motion.div>
  );
}

function ChipIcon({ kind }) {
  const Icon = KIND[kind].icon;
  return <Icon className="size-3 shrink-0" aria-label={KIND[kind].label} />;
}

function EventPopover({ event, agency, onOpenGrant, children }) {
  return (
    <Popover>
      <PopoverTrigger asChild>{children}</PopoverTrigger>
      <PopoverContent className="w-80" align="start">
        <EventDetail event={event} agency={agency} onOpenGrant={onOpenGrant} />
      </PopoverContent>
    </Popover>
  );
}

/** Everything about one date, with a way back to the grant and to the page of the notice it came from. */
function EventDetail({ event: e, agency, onOpenGrant, showDate = true }) {
  const o = e.opportunity;
  const Icon = KIND[e.kind].icon;
  const ai = e.kind === "key_date" || e.kind === "step";
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = useCallback(async () => {
    setBusy(true);
    setErr("");
    try { await downloadGrantCalendar(agency.id, o.id); } catch (x) { setErr(x.message); } finally { setBusy(false); }
  }, [agency.id, o.id]);
  return (
    <div className="flex flex-col gap-2 text-[13.5px]">
      <p className={cn("flex items-center gap-1.5 text-[12px] font-medium", isUrgent(e) ? "text-urgent" : "text-muted-foreground")}>
        <Icon className="size-3.5" /> {KIND[e.kind].label}
        <span className="ml-auto font-mono tabular-nums">{relative(e.date)}</span>
      </p>
      {showDate && <p className="font-mono text-[12px] text-muted-foreground">{longDate(e.date)}</p>}
      <p className="text-[15px] leading-snug font-extrabold text-pine-ink">{ai ? e.title : o.title}</p>
      {ai && <p className="text-muted-foreground">For <span className="font-medium text-foreground">{o.title}</span></p>}
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge className="bg-pine-100 text-[11px] text-pine">{STATUS[e.status] || e.status}</Badge>
        {o.number && <span className="font-mono text-[11.5px] text-muted-foreground">{o.number}</span>}
      </div>
      {e.detail && <p className="leading-relaxed">{e.detail}</p>}
      {e.source && (
        <a href={documentUrl(o.id, e.source.doc_id, e.source.page)} target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-1 self-start text-[12.5px] font-medium text-pine-500 underline decoration-pine-300 underline-offset-4 hover:text-pine">
          {e.source.doc_name}, p. {e.source.page} <ExternalLink className="size-3" />
        </a>
      )}
      {ai && <p className="text-[12px] text-muted-foreground italic">Suggested by AI from the notice. Check it before you rely on it.</p>}
      <div className="mt-1 flex flex-wrap gap-2">
        <Button size="sm" onClick={() => onOpenGrant(o, e.status)}>Open grant</Button>
        <Button size="sm" variant="outline" onClick={save} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : <CalendarPlus />} This grant (.ics)
        </Button>
        {o.url && (
          <Button asChild size="sm" variant="ghost">
            <a href={o.url} target="_blank" rel="noopener noreferrer">Listing <ExternalLink /></a>
          </Button>
        )}
      </div>
      {err && <p className="text-[12.5px] text-urgent" role="alert">{err}</p>}
    </div>
  );
}

/** Dates in order, grouped by month; past dates fold away. Works at any width. */
function AgendaList({ events, agency, onOpenGrant }) {
  const [showPast, setShowPast] = useState(false);
  const today = todayIso();
  const past = events.filter((e) => e.date < today);
  const shown = showPast ? events : events.filter((e) => e.date >= today);
  const groups = [];
  for (const e of shown) {
    const month = e.date.slice(0, 7);
    let g = groups.at(-1);
    if (!g || g.month !== month) groups.push((g = { month, days: [] }));
    let d = g.days.at(-1);
    if (!d || d.date !== e.date) g.days.push((d = { date: e.date, events: [] }));
    d.events.push(e);
  }
  return (
    <div className="flex flex-col gap-8">
      {past.length > 0 && (
        <Button variant="outline" size="sm" className="self-start bg-white" onClick={() => setShowPast(!showPast)}>
          {showPast ? "Hide past dates" : `Show ${past.length} past date${past.length === 1 ? "" : "s"}`}
        </Button>
      )}
      {groups.length === 0 && <p className="text-muted-foreground">No upcoming dates.</p>}
      {groups.map((g) => (
        <section key={g.month} aria-label={parse(`${g.month}-01`).toLocaleDateString("en-US", { month: "long", year: "numeric" })}>
          <h3 className="mb-3 border-b-2 border-pine pb-1.5 font-mono text-[12px] tracking-wide text-pine uppercase">
            {parse(`${g.month}-01`).toLocaleDateString("en-US", { month: "long", year: "numeric" })}
          </h3>
          <motion.ol className="flex flex-col gap-3" initial="hidden" animate="show"
            variants={{ show: { transition: { staggerChildren: 0.04 } } }}>
            {g.days.map((d) => {
              const dt = parse(d.date);
              const isToday = d.date === today;
              return (
                <motion.li key={d.date} className="grid grid-cols-[56px_minmax(0,1fr)] gap-3 sm:grid-cols-[72px_minmax(0,1fr)]"
                  variants={{ hidden: { opacity: 0, y: 6 }, show: { opacity: 1, y: 0 } }}>
                  <div className={cn("pt-1 text-center", d.date < today && "opacity-55")}>
                    <p className={cn("font-display text-[34px] leading-none font-extrabold tabular-nums", isToday ? "text-blaze-deep" : "text-pine")}>{dt.getDate()}</p>
                    <p className="mt-1 font-mono text-[11px] text-muted-foreground uppercase">{isToday ? "Today" : WEEKDAYS[dt.getDay()]}</p>
                  </div>
                  <ul className="flex flex-col gap-2">
                    {d.events.map((e) => (
                      <li key={e.id}>
                        <Card className={cn("gap-0 border-l-4 bg-white px-4 py-3",
                          e.kind === "deadline" ? (isUrgent(e) ? "border-l-urgent" : "border-l-pine") :
                          e.kind === "forecast" ? "border-l-pine-300 border-dashed" :
                          e.kind === "step" ? "border-l-blaze" : "border-l-pine-300",
                          d.date < today && "opacity-60")}>
                          <EventDetail event={e} agency={agency} onOpenGrant={onOpenGrant} showDate={false} />
                        </Card>
                      </li>
                    ))}
                  </ul>
                </motion.li>
              );
            })}
          </motion.ol>
        </section>
      ))}
    </div>
  );
}
