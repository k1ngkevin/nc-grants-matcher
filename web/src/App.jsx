import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, BookOpen, Check, Download, Loader2 } from "lucide-react";
import { api, fmtDate, store } from "./api.js";
import GrantCard from "./GrantCard.jsx";
import ScoreFilter from "./ScoreFilter.jsx";
import { EmailSignup, Filters, ImproveMatches } from "./Sidebar.jsx";
import Glossary from "./Glossary.jsx";
import AgencyPicker, { RidgeMark } from "./AgencyPicker.jsx";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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

  const goHome = () => {
    setAgencyId(null);
    setData(null);
    store.set("agency", null);
    window.history.replaceState(null, "", "/");
  };

  if (metaError) {
    return (
      <Backdrop>
        <Alert variant="destructive" className="settle max-w-md bg-white shadow-lg">
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
        <p className="flex items-center gap-2 rounded-full bg-white/80 px-4 py-2 text-sm text-ridge shadow-sm backdrop-blur">
          <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> Loading open grants
        </p>
      </Backdrop>
    );
  }

  const last = meta.last_ingest;
  const counts = data?.counts || {};

  return (
    <div className="flex min-h-screen flex-col">
      <header className="bg-ridge text-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
          <a href="/" className="flex items-center gap-3 rounded-md text-white no-underline focus-visible:ring-2 focus-visible:ring-white/60 focus-visible:outline-none"
            onClick={(e) => { e.preventDefault(); goHome(); }}>
            <RidgeMark className="size-9 shrink-0" />
            <span className="leading-tight">
              <strong className="block text-[17px] font-semibold">NC Federal Funds Matchmaker</strong>
              <small className="hidden text-[13px] text-white/70 sm:block">Federal grants your agency can win, ranked and explained</small>
            </span>
          </a>
          <div className="flex flex-wrap items-center gap-4">
            {last && (
              <span className="hidden text-[13px] text-white/75 md:inline" title={`Source: ${last.source}`}>
                {meta.opportunity_count.toLocaleString()} open grants, updated {fmtDate(last.as_of)}
              </span>
            )}
            <Button variant="ghost" size="sm" className="text-white hover:bg-white/10 hover:text-white" onClick={() => setShowGlossary(true)}>
              <BookOpen /> Grant types explained
            </Button>
          </div>
        </div>
      </header>

      {meta.sample_data && (
        <div className="border-b border-gold/20 bg-gold-bg px-4 py-2 text-center text-sm text-gold">
          <strong>Demo mode.</strong> These are SAMPLE grants, not live ones. Run <code>python -m app.ingest</code> on a machine
          with internet access to load live Grants.gov data.
        </div>
      )}

      {!agency ? (
        <Landing meta={meta} onPick={(id) => { setAgencyId(id); setView("recommended"); }} />
      ) : (
        <main className="mx-auto grid w-full max-w-7xl items-start gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[320px_minmax(0,1fr)]">
          <aside className="order-2 flex flex-col gap-4 lg:order-1">
            <Card className="gap-0 py-4">
              <CardContent className="px-4">
                <Label htmlFor="agency-select" className="mb-2 text-muted-foreground">Your agency</Label>
                <AgencyPicker id="agency-select" agencies={meta.agencies} value={agencyId}
                  onChange={(id) => { setAgencyId(id); setView("recommended"); setLimit(25); setFocusOpp(null); }} />
              </CardContent>
            </Card>
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

          <section className="order-1 min-w-0 lg:order-2">
            <Tabs value={view} onValueChange={(v) => { setView(v); setLimit(25); setFocusOpp(null); }}>
              <TabsList variant="line" className="h-auto w-full justify-start gap-1 overflow-x-auto border-b p-0">
                {TABS.map(([key, label]) => (
                  <TabsTrigger key={key} value={key} className="group flex-none px-3 pt-2 pb-3 text-[15px] data-[state=active]:text-ridge">
                    {label}
                    <Badge variant="secondary" className="min-w-6 px-1.5 tabular-nums group-data-[state=active]:bg-ridge group-data-[state=active]:text-white">{counts[key] ?? "–"}</Badge>
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>

            {view === "recommended" && !focusOpp && (
              <ScoreFilter filters={filters} onChange={changeFilters} belowScoreCount={loading ? null : data?.below_score_count} />
            )}

            <div className="flex flex-wrap items-center justify-between gap-3 py-4">
              <div className="text-[15px]">{data ? <Summary data={data} view={view} agency={agency} /> : " "}</div>
              <div className="flex items-center gap-2">
                <Label htmlFor="sort" className="text-muted-foreground">Sort</Label>
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
              <Alert className="mb-3 border-forecast/30 bg-forecast-bg">
                <AlertDescription className="flex flex-wrap items-center gap-x-2 text-foreground">
                  Showing the grant from your email.
                  <Button variant="link" className="h-auto p-0" onClick={() => setFocusOpp(null)}>Show all results</Button>
                </AlertDescription>
              </Alert>
            )}
            {error && (
              <Alert variant="destructive" className="mb-3 bg-urgent-bg">
                <AlertTriangle />
                <AlertTitle>Couldn't load grants</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            {loading && !data && (
              <div className="flex flex-col gap-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-40 rounded-xl bg-white" />)}</div>
            )}

            {data && data.results.length === 0 && !loading && (
              <EmptyState view={view} filters={filters} setFilters={changeFilters} agency={agency} />
            )}

            <div className={`flex flex-col gap-3 transition-opacity ${loading ? "opacity-55" : ""}`}>
              {data?.results
                .filter((r) => !focusOpp || r.opportunity.id === focusOpp)
                .map((r) => (
                  <GrantCard key={r.opportunity.id} result={r} view={view} agency={agency} meta={meta}
                    onDecide={decide} startExpanded={r.opportunity.id === focusOpp} />
                ))}
            </div>

            {data && !focusOpp && data.total > data.results.length && (
              <Button variant="outline" className="mt-3 w-full bg-white" onClick={() => setLimit(limit + 25)}>
                Show {Math.min(25, data.total - data.results.length)} more of {data.total - data.results.length} remaining
              </Button>
            )}

            <p className="mt-6 mb-2 max-w-prose text-[13px] text-muted-foreground">
              Scores are recommendations. Your team makes every decision. Only grants that are still open, at least{" "}
              {`$${(meta.financial_floor / 1000).toFixed(0)}K`}, and open to{" "}
              {agency.applicant === "higher_ed" ? "public colleges and universities" : "state governments"} are shown.
            </p>
          </section>
        </main>
      )}

      <Glossary meta={meta} open={showGlossary} onOpenChange={setShowGlossary} />
    </div>
  );
}

function Backdrop({ children }) {
  return <div className="ridge-backdrop flex min-h-screen items-start justify-center px-4 pt-[22vh]">{children}</div>;
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
      {urgent > 0 && <>, <span className="font-semibold text-urgent">{urgent} closing within 14 days</span></>}
    </span>
  );
}

function EmptyState({ view, filters, setFilters, agency }) {
  if (view !== "recommended") {
    const how = view === "save" ? "Save for later" : view === "pursue" ? "Pursue" : "Dismiss";
    return (
      <Card className="items-center py-10 text-center text-muted-foreground">
        <p>Nothing here yet. Choose <strong className="text-foreground">{how}</strong> on a recommended grant to add it.</p>
      </Card>
    );
  }
  return (
    <Card className="items-center gap-3 py-10 text-center">
      <p className="font-semibold">No grants for {agency.short} with these filters</p>
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

function Landing({ meta, onPick }) {
  const [choice, setChoice] = useState("");
  const floor = `$${(meta.financial_floor / 1000).toFixed(0)}K`;
  return (
    <main className="ridge-backdrop flex-1">
      <div className="mx-auto max-w-7xl px-4 pt-[8vh] pb-[38vh] sm:px-6">
        <div className="settle max-w-xl">
          <h1 className="text-4xl leading-[1.08] font-bold tracking-tight text-ridge sm:text-5xl">
            Find federal grants your agency can win
          </h1>
          <p className="mt-4 max-w-lg text-lg text-ridge/80">
            Pick your agency to see open federal grants you're eligible for, ranked by fit, each with a plain-English reason.
          </p>

          <form className="mt-8 rounded-xl bg-white/95 p-5 shadow-[0_12px_40px_-12px_rgba(30,53,66,0.35)] backdrop-blur sm:p-6"
            onSubmit={(e) => { e.preventDefault(); if (choice) onPick(choice); }}>
            <Label htmlFor="landing-agency" className="mb-2 text-sm">Which agency are you with?</Label>
            <div className="flex flex-col gap-2 sm:flex-row">
              <div className="min-w-0 flex-1">
                <AgencyPicker id="landing-agency" agencies={meta.agencies} value={choice} onChange={setChoice} autoFocus />
              </div>
              <Button type="submit" size="lg" className="h-11 shrink-0" disabled={!choice}>Show my grants</Button>
            </div>
            <ul className="mt-5 grid gap-x-6 gap-y-2 border-t pt-4 text-sm sm:grid-cols-2">
              {[
                "Only grants your agency is eligible for",
                `No expired deadlines or awards under ${floor}`,
                "A clear reason for every match, and you make the call",
                "An optional email with the top grants each week",
              ].map((t) => (
                <li key={t} className="flex gap-2"><Check className="mt-0.5 size-4 shrink-0 text-primary" />{t}</li>
              ))}
            </ul>
          </form>

          {meta.last_ingest && (
            <p className="mt-4 text-sm text-ridge/70">
              {meta.opportunity_count.toLocaleString()} open federal grants from Grants.gov, updated {fmtDate(meta.last_ingest.as_of)}.
            </p>
          )}
        </div>
      </div>
    </main>
  );
}
