import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "motion/react";
import { AlertTriangle, BookOpen, Download, Loader2 } from "lucide-react";
import { api, fmtDate, store } from "./api.js";
import GrantCard from "./GrantCard.jsx";
import ScoreFilter from "./ScoreFilter.jsx";
import { EmailSignup, Filters, ImproveMatches } from "./Sidebar.jsx";
import Glossary from "./Glossary.jsx";
import AgencyPicker, { BridgeMark } from "./AgencyPicker.jsx";
import ContourField from "./ContourField.jsx";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

const ALL_TIMING = ["urgent", "standard", "later", "forecasted"];
const TABS = [
  ["recommended", "Recommended"],
  ["save", "Saved"],
  ["pursue", "Pursuing"],
  ["dismiss", "Dismissed"],
];
const EASE = [0.2, 0.7, 0.2, 1];

function defaultFilters(meta) {
  return {
    min_award: meta.financial_floor,
    timing: ALL_TIMING,
    q: "",
    federal_agency: "",
    no_match_only: false,
    include_unknown_amount: true,
    min_score: meta.default_min_score,
    include_lower_scores: false,
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
        const defaults = defaultFilters(m);
        const saved = store.get("filters", {}) || {};
        const savedScore = Number(saved.min_score);
        setFilters({
          ...defaults,
          ...saved,
          min_score: Number.isInteger(savedScore) && savedScore > 0 && savedScore <= 100 ? savedScore : defaults.min_score,
          // Keep the previous "show weaker matches" preference while retaining a real threshold.
          include_lower_scores: typeof saved.include_lower_scores === "boolean" ? saved.include_lower_scores : saved.min_score === 0,
          q: "",
        });
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

  const changeFilters = (next) => {
    setFilters(next);
    setLimit(25);
    setFocusOpp(null);
  };

  const pickAgency = (id) => {
    setAgencyId(id);
    setView("recommended");
    setLimit(25);
    setFocusOpp(null);
  };

  const goHome = () => {
    setAgencyId(null);
    setData(null);
    store.set("agency", null);
    window.history.replaceState(null, "", "/");
  };

  if (metaError) {
    return (
      <Backdrop>
        <Alert variant="destructive" className="max-w-md bg-white">
          <AlertTriangle />
          <AlertTitle>The grants server isn't responding</AlertTitle>
          <AlertDescription>
            <p>{metaError}</p>
            <p>Check that the server is running on port 8000, then reload this page.</p>
          </AlertDescription>
        </Alert>
      </Backdrop>
    );
  }
  if (!meta || !filters) {
    return (
      <Backdrop>
        <p className="flex items-center gap-2 text-sm text-fog/80">
          <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> Loading open grants
        </p>
      </Backdrop>
    );
  }

  const counts = data?.counts || {};
  const topBar = <TopBar meta={meta} onHome={goHome} onGlossary={() => setShowGlossary(true)} />;

  return (
    <div className="flex min-h-screen flex-col">
      {meta.sample_data && (
        <div className="bg-blaze-tint px-4 py-2 text-center text-sm text-pine-ink">
          <strong className="font-extrabold">Demo mode.</strong> These are sample grants, not live ones. Run <code>python -m app.ingest</code> on a machine
          with internet access to load live Grants.gov data.
        </div>
      )}

      {!agency ? (
        <Landing meta={meta} topBar={topBar} onPick={pickAgency} />
      ) : (
        <>
          <header className="topo-sky relative isolate overflow-hidden text-fog">
            <div className="survey-grid absolute inset-0 -z-10" aria-hidden="true" />
            <ContourField className="-z-10 opacity-45 [mask-image:linear-gradient(to_right,rgb(0_0_0/0.3)_20%,black_75%)]" />
            {topBar}
            <div className="mx-auto max-w-7xl px-4 pt-8 sm:px-6 sm:pt-12">
              <div className="flex flex-wrap items-end justify-between gap-x-10 gap-y-6">
                <div className="min-w-0 max-w-3xl">
                  <h1 className="display-light text-[clamp(2.4rem,5.5vw,4.5rem)] leading-[0.98] tracking-[-0.02em]">{agency.name}</h1>
                  <p className="mt-4 text-lg text-fog/80" aria-live="polite">
                    {data ? <Summary data={data} view={view} agency={agency} /> : " "}
                  </p>
                </div>
                <div className="w-full sm:w-80">
                  <Label htmlFor="agency-select" className="mb-2 text-[13px] font-normal text-fog/70">Change agency</Label>
                  <AgencyPicker id="agency-select" agencies={meta.agencies} value={agencyId} onChange={pickAgency}
                    className="border-fog/20 bg-fog/10 text-fog hover:bg-fog/15 hover:text-fog" />
                </div>
              </div>

              <Tabs value={view} onValueChange={(v) => { setView(v); setLimit(25); setFocusOpp(null); }} className="mt-10">
                <TabsList variant="line" className="h-auto w-full justify-start gap-6 overflow-x-auto rounded-none p-0">
                  {TABS.map(([key, label]) => (
                    <TabsTrigger key={key} value={key}
                      className="group flex-none px-0 pt-1 pb-4 text-[15px] text-fog/65 after:bottom-0 after:h-[3px] after:bg-blaze hover:text-fog data-[state=active]:font-extrabold data-[state=active]:text-fog">
                      {label}
                      <Badge className="min-w-6 bg-fog/12 px-1.5 font-mono text-[11px] text-fog tabular-nums group-data-[state=active]:bg-blaze group-data-[state=active]:text-pine-ink">
                        {counts[key] ?? "–"}
                      </Badge>
                    </TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
            </div>
          </header>

          <main className="fog-field flex-1">
            <div className="mx-auto grid w-full max-w-7xl items-start gap-8 px-4 py-8 sm:px-6 lg:grid-cols-[300px_minmax(0,1fr)]">
              <aside className="order-2 flex flex-col gap-4 lg:order-1">
                <Filters
                  meta={meta}
                  filters={filters}
                  facets={data?.facets}
                  onChange={changeFilters}
                  onReset={() => changeFilters(defaultFilters(meta))}
                />
                <EmailSignup meta={meta} agency={agency} filters={{ ...filters, q: debouncedQ }} />
                <ImproveMatches agency={agency} onChanged={load} />
              </aside>

              <section className="order-1 min-w-0 lg:order-2" aria-label="Grants">
                <div className="mb-5 flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
                  {view === "recommended" && !focusOpp ? (
                    <ScoreFilter filters={filters} onChange={changeFilters} belowScoreCount={loading ? null : data?.below_score_count} />
                  ) : <span />}
                  <div className="flex items-center gap-2">
                    <Label htmlFor="sort" className="font-normal text-muted-foreground">Sort</Label>
                    <Select value={filters.sort} onValueChange={(v) => setFilters({ ...filters, sort: v })}>
                      <SelectTrigger id="sort" size="sm" className="bg-white"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="score">Best match</SelectItem>
                        <SelectItem value="deadline">Deadline (soonest)</SelectItem>
                        <SelectItem value="amount">Largest award</SelectItem>
                      </SelectContent>
                    </Select>
                    <Button variant="outline" size="sm" className="bg-white" onClick={exportCsv} disabled={!data?.total}>
                      <Download /> Download CSV
                    </Button>
                  </div>
                </div>

                {focusOpp && (
                  <Alert className="mb-4 border-pine-300 bg-pine-100">
                    <AlertDescription className="flex flex-wrap items-center gap-x-2 text-foreground">
                      Showing the grant from your email.
                      <Button variant="link" className="h-auto p-0" onClick={() => setFocusOpp(null)}>Show all results</Button>
                    </AlertDescription>
                  </Alert>
                )}
                {error && (
                  <Alert variant="destructive" className="mb-4 bg-urgent-bg">
                    <AlertTriangle />
                    <AlertTitle>Couldn't load grants</AlertTitle>
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                )}
                {loading && !data && (
                  <div className="flex flex-col gap-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-44 rounded-lg bg-white" />)}</div>
                )}

                {data && data.results.length === 0 && !loading && (
                  <EmptyState view={view} filters={filters} setFilters={changeFilters} agency={agency} />
                )}

                <ol className={`flex flex-col gap-3 transition-opacity motion-reduce:transition-none ${loading ? "opacity-55" : ""}`}>
                  {data?.results
                    .filter((r) => !focusOpp || r.opportunity.id === focusOpp)
                    .map((r) => (
                      <li key={r.opportunity.id}>
                        <GrantCard result={r} view={view} agency={agency} meta={meta}
                          onDecide={decide} startExpanded={r.opportunity.id === focusOpp} />
                      </li>
                    ))}
                </ol>

                {data && !focusOpp && data.total > data.results.length && (
                  <Button variant="outline" className="mt-4 h-11 w-full bg-white" onClick={() => setLimit(limit + 25)}>
                    Show {Math.min(25, data.total - data.results.length)} more of {data.total - data.results.length} remaining
                  </Button>
                )}

                <p className="mt-8 mb-2 max-w-prose text-[13px] text-muted-foreground">
                  Scores are recommendations. Your team makes every decision. Only grants that are still open, at least{" "}
                  {`$${(meta.financial_floor / 1000).toFixed(0)}K`}, and open to{" "}
                  {agency.applicant === "higher_ed" ? "public colleges and universities" : "state governments"} are shown.
                </p>
              </section>
            </div>
          </main>
        </>
      )}

      <Glossary meta={meta} open={showGlossary} onOpenChange={setShowGlossary} />
    </div>
  );
}

function TopBar({ meta, onHome, onGlossary }) {
  const last = meta.last_ingest;
  return (
    <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-4 sm:px-6">
      <a href="/" className="flex items-center gap-3 rounded-md text-fog no-underline focus-visible:ring-2 focus-visible:ring-blaze focus-visible:outline-none"
        onClick={(e) => { e.preventDefault(); onHome(); }}>
        <BridgeMark className="size-9 shrink-0" />
        <span className="text-[17px] leading-tight font-extrabold tracking-[-0.01em]">NC Federal Funds Matchmaker</span>
      </a>
      <div className="flex items-center gap-5">
        {last && (
          <span className="hidden text-[13px] text-fog/65 md:inline" title={`Source: ${last.source}`}>
            {meta.opportunity_count.toLocaleString()} open grants, updated {fmtDate(last.as_of)}
          </span>
        )}
        <Button variant="ghost" size="sm" className="text-fog hover:bg-fog/10 hover:text-fog focus-visible:ring-blaze/60" onClick={onGlossary}>
          <BookOpen /> Grant types explained
        </Button>
      </div>
    </div>
  );
}

function Backdrop({ children }) {
  return (
    <div className="topo-sky relative isolate flex min-h-screen items-start justify-center overflow-hidden px-4 pt-[22vh]">
      <div className="survey-grid absolute inset-0 -z-10" aria-hidden="true" />
      <ContourField className="-z-10 opacity-60" />
      {children}
    </div>
  );
}

function Summary({ data, view, agency }) {
  const urgent = data.facets.timing.urgent;
  if (view !== "recommended") {
    const label = { save: "saved", pursue: "being pursued", dismiss: "dismissed" }[view];
    return <><strong className="font-extrabold text-fog">{data.total}</strong> grants {label} by {agency.short}</>;
  }
  return (
    <>
      <strong className="font-extrabold text-fog">{data.total}</strong> open grants match {agency.short}
      {urgent > 0 && <>, and <strong className="font-extrabold text-blaze">{urgent} close within 14 days</strong></>}
    </>
  );
}

function EmptyState({ view, filters, setFilters, agency }) {
  if (view !== "recommended") {
    const how = view === "save" ? "Save for later" : view === "pursue" ? "Pursue" : "Dismiss";
    return (
      <Card className="items-center border-dashed bg-white/60 py-12 text-center text-muted-foreground">
        <p>Nothing here yet. Choose <strong className="font-extrabold text-foreground">{how}</strong> on a recommended grant to add it.</p>
      </Card>
    );
  }
  return (
    <Card className="items-center gap-3 border-dashed bg-white/60 py-12 text-center">
      <p className="display-light text-3xl text-pine">No grants for {agency.short} with these filters</p>
      <p className="max-w-md text-sm text-muted-foreground">
        Widen the filters or include lower scores. Adding your active projects under "Improve your matches" also sharpens the results.
      </p>
      <div className="flex gap-2">
        {!filters.include_lower_scores && filters.min_score > 0 && (
          <Button onClick={() => setFilters({ ...filters, include_lower_scores: true })}>Include scores below {filters.min_score}</Button>
        )}
        {filters.q && <Button variant="outline" onClick={() => setFilters({ ...filters, q: "" })}>Clear search</Button>}
      </div>
    </Card>
  );
}

const HEADLINE = ["Find the federal", "grants your agency", "can win."];

const rise = {
  hidden: { opacity: 0, y: 28 },
  show: { opacity: 1, y: 0, transition: { duration: 0.8, ease: EASE } },
};

function Landing({ meta, topBar, onPick }) {
  const [choice, setChoice] = useState("");
  const floor = `$${(meta.financial_floor / 1000).toFixed(0)}K`;
  const facts = [
    ["Eligible only", "Grants open to state agencies, or to public universities if that's who you are."],
    [`Open, and ${floor} or more`, "Expired deadlines and small awards are screened out every morning."],
    ["A reason for every match", "Each grant says why it fits and where it falls short. Your team decides."],
    ["Email, if you want it", "The top matches for your agency, sent daily, weekly or monthly."],
  ];

  return (
    <main className="flex flex-1 flex-col">
      <section className="topo-sky relative isolate flex min-h-[92svh] flex-col overflow-hidden text-fog">
        <div className="survey-grid absolute inset-0 -z-10" aria-hidden="true" />
        <ContourField draw className="-z-10 [mask-image:linear-gradient(to_right,rgb(0_0_0/0.35)_15%,black_65%)]" />
        {topBar}

        <motion.div className="mx-auto flex w-full max-w-7xl flex-1 flex-col justify-center px-4 pt-10 pb-40 sm:px-6"
          initial="hidden" animate="show" variants={{ show: { transition: { delayChildren: 0.55, staggerChildren: 0.12 } } }}>
          <h1 className="display-light max-w-5xl text-[clamp(3.1rem,9vw,8.25rem)] leading-[0.9] tracking-[-0.035em]">
            {HEADLINE.map((line) => (
              <motion.span key={line} variants={rise} className="block">{line}</motion.span>
            ))}
          </h1>

          <motion.p variants={rise} className="mt-8 max-w-xl text-lg text-fog/80 sm:text-xl">
            Pick your agency to see every open federal grant you're eligible for, ranked by fit, each with a plain-English reason.
          </motion.p>

          <motion.form variants={rise} className="mt-10 max-w-2xl" onSubmit={(e) => { e.preventDefault(); if (choice) onPick(choice); }}>
            <Label htmlFor="landing-agency" className="mb-2.5 text-sm font-normal text-fog/75">Which agency are you with?</Label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <div className="min-w-0 flex-1">
                <AgencyPicker id="landing-agency" agencies={meta.agencies} value={choice} onChange={setChoice} autoFocus className="h-12 text-[15px]" />
              </div>
              <Button type="submit" variant="blaze" size="lg" className="h-12 shrink-0 px-7 text-[15px]" disabled={!choice}>Show my grants</Button>
            </div>
            {meta.last_ingest && (
              <p className="mt-4 text-sm text-fog/60">
                {meta.opportunity_count.toLocaleString()} open federal grants from Grants.gov, updated {fmtDate(meta.last_ingest.as_of)}.
              </p>
            )}
          </motion.form>
        </motion.div>

        <RidgeEdge />
      </section>

      <section className="fog-field">
        <ul className="mx-auto grid max-w-7xl gap-x-10 gap-y-8 px-4 pt-6 pb-20 sm:grid-cols-2 sm:px-6 lg:grid-cols-4">
          {facts.map(([title, body]) => (
            <li key={title} className="border-t-2 border-pine pt-4">
              <p className="text-lg leading-snug font-extrabold text-pine">{title}</p>
              <p className="mt-2 text-[15px] text-muted-foreground">{body}</p>
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}

/** The hero's lower edge: two ridgelines, the near one in the page's fog color. */
function RidgeEdge() {
  return (
    <svg viewBox="0 0 1600 180" preserveAspectRatio="none" aria-hidden="true" className="absolute inset-x-0 bottom-0 -z-10 h-[16vh] min-h-24 w-full">
      <path className="fill-pine-700/50" d="M0 92 C120 70 210 40 330 58 S560 120 700 84 S930 18 1080 40 S1330 110 1450 74 S1560 52 1600 60 V180 H0 Z" />
      <path className="fill-fog" d="M0 138 C150 118 260 96 400 112 S640 160 800 132 S1050 84 1200 104 S1440 150 1600 120 V180 H0 Z" />
    </svg>
  );
}
