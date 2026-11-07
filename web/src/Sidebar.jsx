import { useEffect, useState } from "react";
import { CheckCircle2, ChevronDown, Mail, Search, Upload, X } from "lucide-react";
import { api, store } from "./api.js";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const TIMING = [
  ["urgent", "Closes within 14 days", "bg-urgent"],
  ["standard", "Closes in 15–60 days", "bg-pine"],
  ["later", "Closes in 60+ days", "bg-pine-300"],
  ["forecasted", "Forecast (coming soon)", "border border-dashed border-pine-500"],
];
const AWARD_OPTIONS = [50_000, 100_000, 250_000, 1_000_000, 5_000_000];
const ALL_DEPTS = "__all";

function FieldLabel({ htmlFor, children, className }) {
  return <Label htmlFor={htmlFor} className={cn("mb-1.5 text-[13px] text-muted-foreground", className)}>{children}</Label>;
}

function CheckRow({ id, checked, onChange, children, count }) {
  return (
    <div className="flex items-center gap-2.5 py-1">
      <Checkbox id={id} checked={checked} onCheckedChange={(v) => onChange(v === true)} />
      <Label htmlFor={id} className="flex-1 cursor-pointer gap-2 text-sm font-normal">{children}</Label>
      {count != null && <span className="text-[13px] text-muted-foreground tabular-nums">{count}</span>}
    </div>
  );
}

export function Filters({ meta, filters, facets, onChange, onReset }) {
  const set = (patch) => onChange({ ...filters, ...patch });
  const toggleTiming = (t) => {
    const next = filters.timing.includes(t) ? filters.timing.filter((x) => x !== t) : [...filters.timing, t];
    set({ timing: next.length ? next : [t] });
  };
  const depts = Object.entries(facets?.federal_agency || {});

  return (
    <Card className="gap-4 py-4">
      <CardHeader className="px-4">
        <CardTitle>Filters</CardTitle>
        <CardAction>
          <Button variant="link" size="sm" className="h-auto p-0" onClick={onReset}>Reset</Button>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-4">
        <div>
          <FieldLabel htmlFor="kw">Search</FieldLabel>
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input id="kw" type="search" className="pl-8" placeholder="broadband, flood, literacy" value={filters.q} onChange={(e) => set({ q: e.target.value })} />
          </div>
        </div>

        <div>
          <FieldLabel htmlFor="min-award">Minimum award</FieldLabel>
          <Select value={String(filters.min_award)} onValueChange={(v) => set({ min_award: Number(v) })}>
            <SelectTrigger id="min-award" className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              {AWARD_OPTIONS.filter((v) => v >= meta.financial_floor).map((v) => (
                <SelectItem key={v} value={String(v)}>{v >= 1_000_000 ? `$${v / 1_000_000}M` : `$${v / 1000}K`} or more</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <fieldset>
          <legend className="mb-1 text-[13px] font-medium text-muted-foreground">Deadline</legend>
          {TIMING.map(([key, label, dot]) => (
            <CheckRow key={key} id={`timing-${key}`} checked={filters.timing.includes(key)} onChange={() => toggleTiming(key)} count={facets?.timing?.[key] ?? ""}>
              <span className={cn("size-2 shrink-0 rounded-full", dot)} aria-hidden="true" />
              {label}
            </CheckRow>
          ))}
        </fieldset>

        <div>
          <FieldLabel htmlFor="fed">Federal department</FieldLabel>
          <Select value={filters.federal_agency || ALL_DEPTS} onValueChange={(v) => set({ federal_agency: v === ALL_DEPTS ? "" : v })}>
            <SelectTrigger id="fed" className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent position="popper" className="max-h-80">
              <SelectItem value={ALL_DEPTS}>All departments</SelectItem>
              {filters.federal_agency && !depts.some(([d]) => d === filters.federal_agency) && (
                <SelectItem value={filters.federal_agency}>{filters.federal_agency}</SelectItem>
              )}
              {depts.map(([d, n]) => (
                <SelectItem key={d} value={d}>{d} ({n})</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <fieldset>
          <legend className="mb-1 text-[13px] font-medium text-muted-foreground">More options</legend>
          <CheckRow id="opt-nomatch" checked={filters.no_match_only} onChange={(v) => set({ no_match_only: v })}>No matching funds required</CheckRow>
          <CheckRow id="opt-unknown" checked={filters.include_unknown_amount} onChange={(v) => set({ include_unknown_amount: v })}>Include grants with no amount listed</CheckRow>
        </fieldset>
      </CardContent>
    </Card>
  );
}

export function EmailSignup({ meta, agency, filters }) {
  const [email, setEmail] = useState(() => store.get("email", ""));
  const [frequency, setFrequency] = useState("weekly");
  const [topN, setTopN] = useState(10);
  const [customCount, setCustomCount] = useState(false);
  const [state, setState] = useState({ status: "idle" });

  useEffect(() => setState({ status: "idle" }), [agency.id]);

  const { sort, ...searchFilters } = filters;
  const maxGrants = meta.max_digest_grants || 100;
  const validCount = Number.isInteger(topN) && topN >= 1 && topN <= maxGrants;
  const body = { email: email.trim(), agency_id: agency.id, frequency, top_n: topN, filters: searchFilters };

  const submit = async (e) => {
    e.preventDefault();
    if (!validCount) return;
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
    if (!validCount) return;
    try {
      const html = await api.previewEmail({ ...body, email: body.email || "preview@example.gov" });
      const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
      window.open(url, "_blank", "noopener");
    } catch (err) {
      setState({ status: "error", error: err.message });
    }
  };

  const sendTest = async () => {
    if (!validCount) return;
    if (!email.trim()) {
      setState({ status: "error", error: "Enter your work email to send a test." });
      return;
    }
    setState({ status: "busy" });
    try {
      const result = await api.testEmail(body);
      const message = result.delivery.delivered
        ? `Your email provider accepted a test with ${result.grant_count} grants for ${result.email}. Check your inbox and spam folder.`
        : `Email delivery is not configured. A test with ${result.grant_count} grants was saved to the server outbox (${result.delivery.outbox_file}).`;
      setState({ status: "test", message });
    } catch (err) {
      setState({ status: "error", error: err.message });
    }
  };

  if (state.status === "done") {
    const r = state.res;
    return (
      <Card className="gap-3 border-t-4 border-t-pine py-4">
        <CardHeader className="px-4">
          <CardTitle className="flex items-center gap-2 text-pine"><CheckCircle2 className="size-5" /> Subscribed</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 px-4 text-sm">
          {r.confirmed ? (
            <p>
              We'll email up to {r.top_n} top grants for {agency.short} to <b>{r.email}</b> {r.frequency}.{" "}
              {r.delivery?.error ? "The first email didn't go out, so we'll try again within the hour." : "The first one was just sent."}
            </p>
          ) : (
            <p>Check <b>{r.email}</b> for a confirmation link for up to {r.top_n} top grants {r.frequency}. Alerts start once you confirm.</p>
          )}
          {!r.email_enabled && (
            <p className="text-[13px] text-muted-foreground">
              Demo server: email isn't configured, so messages are saved to the server's outbox folder.
              {r.dev_confirm_url && (<> <a className="text-primary underline" href={r.dev_confirm_url} target="_blank" rel="noopener noreferrer">Confirm now (demo)</a></>)}
            </p>
          )}
          <Button variant="link" size="sm" className="h-auto self-start p-0" onClick={() => setState({ status: "idle" })}>Update preferences or add another</Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="gap-3 border-t-4 border-t-pine py-4">
      <CardHeader className="px-4">
        <CardTitle className="flex items-center gap-2"><Mail className="size-4 text-pine" /> Email me the top grants</CardTitle>
        <CardDescription>Public grant matches for {agency.short} with your selected filters. Any email can subscribe; confirm through the emailed link. Internal agency information is excluded.</CardDescription>
      </CardHeader>
      <CardContent className="px-4">
        <form className="flex flex-col gap-3" onSubmit={submit}>
          <div>
            <FieldLabel htmlFor="sub-email">Email address</FieldLabel>
            <Input id="sub-email" type="email" required placeholder="you@agency.nc.gov" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <FieldLabel htmlFor="sub-freq">How often</FieldLabel>
              <Select value={frequency} onValueChange={setFrequency}>
                <SelectTrigger id="sub-freq" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent position="popper" side="bottom" align="start" sideOffset={6}>
                  <SelectItem value="daily">Daily</SelectItem>
                  <SelectItem value="weekly">Weekly</SelectItem>
                  <SelectItem value="biweekly">Every 2 weeks</SelectItem>
                  <SelectItem value="monthly">Monthly</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <FieldLabel htmlFor="sub-n">How many</FieldLabel>
              <Select value={customCount ? "custom" : String(topN)} onValueChange={(v) => {
                setCustomCount(v === "custom");
                if (v !== "custom") setTopN(Number(v));
              }}>
                <SelectTrigger id="sub-n" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {[5, 10, 15, 25].map((n) => <SelectItem key={n} value={String(n)}>Top {n}</SelectItem>)}
                  <SelectItem value="custom">Custom number</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          {customCount && (
            <div>
              <FieldLabel htmlFor="sub-custom-n">Number of grants (1–{maxGrants})</FieldLabel>
              <Input id="sub-custom-n" type="number" required min={1} max={maxGrants} step={1}
                value={topN} onChange={(e) => setTopN(e.target.value === "" ? "" : Number(e.target.value))}
                aria-describedby="sub-count-help" />
            </div>
          )}
          <p id="sub-count-help" className="text-[13px] text-muted-foreground">
            Up to {validCount ? topN : maxGrants} grants per email, highest match score first. If fewer match your filters, we'll send fewer.
            Subscribe again with the same email and agency to update your preferences.
          </p>
          <a href="/subscribe" className="text-sm text-primary underline">Public email signup (no sign-in required)</a>
          {state.status === "test" && <Alert><AlertDescription>{state.message}</AlertDescription></Alert>}
          {state.status === "error" && (
            <Alert variant="destructive" className="bg-urgent-bg py-2"><AlertDescription>{state.error}</AlertDescription></Alert>
          )}
          <Button className="w-full" disabled={state.status === "busy"}>{state.status === "busy" ? "Subscribing…" : "Subscribe"}</Button>
          <Button type="button" variant="link" size="sm" className="h-auto p-0" disabled={!validCount || state.status === "busy"} onClick={preview}>Preview the email</Button>
          <Button type="button" variant="secondary" disabled={!validCount || state.status === "busy"} onClick={sendTest}>Send me a test email</Button>
        </form>
      </CardContent>
    </Card>
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

  const ItemList = ({ items, render, onRemove, label }) => items.length > 0 && (
    <ul className="divide-y rounded-md border text-sm">
      {items.map((x) => (
        <li key={x.id} className="flex items-center justify-between gap-2 py-1.5 pr-1 pl-3">
          <span className="min-w-0 truncate" title={x.description}>{render(x)}</span>
          <Button variant="ghost" size="icon-sm" className="text-muted-foreground hover:text-urgent" onClick={() => onRemove(x)} aria-label={`Remove ${label} ${x.title}`}>
            <X />
          </Button>
        </li>
      ))}
    </ul>
  );

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card className="gap-3 py-4">
        <CollapsibleTrigger className="flex w-full items-start justify-between gap-2 px-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 rounded-md">
          <div>
            <p className="leading-none font-extrabold">Improve your matches</p>
            <p className="mt-1.5 text-[13px] text-muted-foreground">
              {projects.length} project{projects.length === 1 ? "" : "s"}, {docs.length} plan{docs.length === 1 ? "" : "s"} added
            </p>
          </div>
          <ChevronDown className={cn("mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none", open && "rotate-180")} />
        </CollapsibleTrigger>
        {!open && <p className="px-4 text-[13px] text-muted-foreground">Tell us what {agency.short} is working on and matches get sharper for everyone at your agency.</p>}

        <CollapsibleContent className="flex flex-col gap-4 px-4">
          {error && <Alert variant="destructive" className="bg-urgent-bg py-2"><AlertDescription>{error}</AlertDescription></Alert>}

          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-extrabold text-pine">Active projects</h3>
            <ItemList items={projects} label="project" render={(x) => x.title} onRemove={(x) => run(() => api.deleteProject(agency.id, x.id))} />
            <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.addProject(agency.id, p); setP({ title: "", description: "" }); }); }}>
              <Input placeholder="Project name" aria-label="Project name" value={p.title} onChange={(e) => setP({ ...p, title: e.target.value })} required minLength={3} maxLength={150} />
              <Textarea placeholder="What it does and what it needs, e.g. 'Replace lead service lines in 12 rural water systems; need $4M for construction.'" rows={3}
                aria-label="Project description" value={p.description} onChange={(e) => setP({ ...p, description: e.target.value })} required minLength={10} maxLength={4000} />
              <Button size="sm" variant="secondary" className="self-end">Add project</Button>
            </form>
          </section>

          <Separator />

          <section className="flex flex-col gap-2">
            <h3 className="text-sm font-extrabold text-pine">Strategic plan or mandates</h3>
            <ItemList items={docs} label="plan" onRemove={(x) => run(() => api.deleteDocument(agency.id, x.id))}
              render={(x) => <>{x.title} <span className="text-muted-foreground">({Math.round(x.characters / 1000)}K chars)</span></>} />
            <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.addDocument(agency.id, d); setD({ title: "", content: "" }); }); }}>
              <Input placeholder="Title, e.g. 2025-2027 Strategic Plan" aria-label="Plan title" value={d.title} onChange={(e) => setD({ ...d, title: e.target.value })} required minLength={3} maxLength={200} />
              <Textarea placeholder="Paste goals, objectives or statutory mandates" aria-label="Plan text" rows={3} value={d.content}
                onChange={(e) => setD({ ...d, content: e.target.value })} required minLength={50} />
              <div className="flex items-center justify-between">
                <Button asChild variant="ghost" size="sm" className="-ml-2 cursor-pointer text-muted-foreground">
                  <label>
                    <Upload /> Upload .txt
                    <input type="file" accept=".txt,.md,.csv" className="sr-only" onChange={(e) => readFile(e.target.files?.[0])} />
                  </label>
                </Button>
                <Button size="sm" variant="secondary">Add plan</Button>
              </div>
            </form>
          </section>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  );
}
