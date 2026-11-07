import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import {
  AlertTriangle,
  CalendarPlus,
  ExternalLink,
  FileText,
  Loader2,
  Mail,
  Phone,
  RefreshCw,
  X,
} from "lucide-react";
import { api, documentUrl, downloadGrantCalendar, fmtDate } from "./api.js";
import ContourField from "./ContourField.jsx";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

const VERDICT = {
  eligible: ["Your agency looks eligible", "border-pine"],
  likely_eligible: ["Your agency is probably eligible", "border-pine-500"],
  unclear: ["Eligibility is unclear", "border-blaze"],
  not_eligible: ["Your agency doesn't look eligible", "border-urgent"],
};
const POLL_MS = 1500;

function shortDate(iso) {
  if (!iso) return null;
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return {
    day: dt.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    rest: `${dt.toLocaleDateString("en-US", { weekday: "short" })}, ${y}`,
  };
}

/** Research a grant's notice documents with AI: eligibility, a dated timeline, requirements, and the PDFs themselves. */
export default function ResearchDialog({
  open,
  onOpenChange,
  result: r,
  agency,
  onDone,
}) {
  const o = r.opportunity;
  const [state, setState] = useState({ status: "loading" }); // loading | running | done | error
  const [tab, setTab] = useState("plan");
  const [doc, setDoc] = useState(null); // { id, page }
  const [calendarError, setCalendarError] = useState("");
  const poll = useRef(null);

  const follow = useCallback((job) => {
    clearTimeout(poll.current);
    if (job.status === "done")
      return setState({ status: "done", data: job.result });
    if (job.status === "error")
      return setState({ status: "error", error: job.error });
    setState({ status: "running", phase: job.phase, started: Date.now() });
    const tick = async () => {
      try {
        const next = await api.researchJob(job.id);
        if (next.status === "running") {
          setState((s) => ({ ...s, phase: next.phase }));
          poll.current = setTimeout(tick, POLL_MS);
        } else follow(next);
      } catch (e) {
        setState({ status: "error", error: e.message });
      }
    };
    poll.current = setTimeout(tick, POLL_MS);
  }, []);

  const start = useCallback(
    async (refresh = false) => {
      setState({ status: "loading" });
      try {
        if (!refresh) {
          const saved = await api.savedResearch(o.id, agency.id);
          if (saved.status === "done")
            return setState({ status: "done", data: saved.result });
        }
        follow(
          await api.startResearch({
            opportunity_id: o.id,
            agency_id: agency.id,
            refresh,
          }),
        );
      } catch (e) {
        setState({ status: "error", error: e.message });
      }
    },
    [o.id, agency.id, follow],
  );

  // Tell the card the grant now has saved research, so its button switches to "View research".
  useEffect(() => {
    if (state.status === "done")
      onDone?.(state.data?.created_at || new Date().toISOString());
  }, [state.status, state.data]);

  // Closing stops polling; the run keeps going on the server and is picked up again on reopen.
  useEffect(() => {
    if (open && state.status !== "done") start();
    return () => clearTimeout(poll.current);
  }, [open]);

  const data = state.data;
  const showDoc = (source) => {
    setDoc({ id: source.doc_id, page: source.page });
    setTab("docs");
  };
  const currentDoc =
    data?.documents?.find((d) => d.id === doc?.id) || data?.documents?.[0];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="flex h-[min(92vh,980px)] flex-col gap-0 overflow-hidden bg-fog p-0 sm:max-w-6xl"
      >
        <Tabs
          value={tab}
          onValueChange={setTab}
          className="flex min-h-0 flex-1 flex-col gap-0"
        >
          <header className="topo-sky relative isolate overflow-hidden px-5 pt-5 text-fog sm:px-8 sm:pt-7">
            <ContourField className="-z-10 opacity-35" />
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <DialogDescription className="text-[13px] text-fog/70">
                  In-depth research for {agency.name}
                </DialogDescription>
                <DialogTitle className="mt-1 text-xl leading-snug font-extrabold tracking-[-0.01em] sm:text-2xl">
                  {o.title}
                </DialogTitle>
              </div>
              <DialogClose asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="shrink-0 text-fog hover:bg-fog/10 hover:text-fog"
                  aria-label="Close"
                >
                  <X />
                </Button>
              </DialogClose>
            </div>
            <TabsList
              variant="line"
              className="mt-5 h-auto w-full justify-start gap-6 rounded-none p-0"
            >
              {[
                ["plan", "Plan"],
                [
                  "docs",
                  `Notice documents${data ? ` (${data.documents.length})` : ""}`,
                ],
              ].map(([key, label]) => (
                <TabsTrigger
                  key={key}
                  value={key}
                  disabled={key === "docs" && !data}
                  className="flex-none px-0 pt-1 pb-3.5 text-[15px] text-fog/65 after:bottom-0 after:h-[3px] after:bg-blaze hover:text-fog data-[state=active]:font-extrabold data-[state=active]:text-fog"
                >
                  {label}
                </TabsTrigger>
              ))}
            </TabsList>
          </header>

          <TabsContent value="plan" className="min-h-0 overflow-y-auto">
            {state.status === "loading" && (
              <Centered>
                <Loader2 className="size-5 animate-spin motion-reduce:[animation-duration:2s]" />
              </Centered>
            )}
            {state.status === "running" && (
              <Running phase={state.phase} started={state.started} />
            )}
            {state.status === "error" && (
              <Centered>
                <Alert variant="destructive" className="max-w-lg bg-white">
                  <AlertTriangle />
                  <AlertTitle>Research didn't finish</AlertTitle>
                  <AlertDescription>
                    <p>{state.error}</p>
                    <Button
                      size="sm"
                      variant="outline"
                      className="mt-2"
                      onClick={() => start(true)}
                    >
                      Try again
                    </Button>
                  </AlertDescription>
                </Alert>
              </Centered>
            )}
            {state.status === "done" && (
              <Plan data={data} r={r} onCite={showDoc} />
            )}
          </TabsContent>

          <TabsContent value="docs" className="flex min-h-0 flex-col">
            {data &&
              (data.documents.length ? (
                <div className="grid min-h-0 flex-1 gap-4 p-4 sm:p-6 lg:grid-cols-[230px_minmax(0,1fr)]">
                  <ul className="flex flex-col gap-1 lg:overflow-y-auto">
                    {data.documents.map((d) => (
                      <li key={d.id}>
                        <button
                          type="button"
                          onClick={() => setDoc({ id: d.id, page: null })}
                          className={cn(
                            "flex w-full items-start gap-2 rounded-md px-3 py-2 text-left text-sm focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
                            d.id === currentDoc?.id
                              ? "bg-white font-extrabold text-pine shadow-[inset_3px_0_0_var(--blaze)]"
                              : "hover:bg-white/60",
                          )}
                        >
                          <FileText className="mt-0.5 size-4 shrink-0 text-pine-500" />
                          <span className="min-w-0">
                            <span className="block break-words">{d.name}</span>
                            <span className="text-[12px] font-normal text-muted-foreground">
                              {d.pages} page{d.pages === 1 ? "" : "s"}
                              {d.folder ? `, ${d.folder}` : ""}
                            </span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  {currentDoc && (
                    <div className="flex min-h-[60vh] flex-col gap-2 lg:min-h-0">
                      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                        <span className="text-muted-foreground">
                          {doc?.page && doc.id === currentDoc.id
                            ? `Page ${doc.page} of ${currentDoc.name}`
                            : currentDoc.name}
                        </span>
                        <Button
                          asChild
                          variant="link"
                          size="sm"
                          className="h-auto p-0"
                        >
                          <a
                            href={documentUrl(o.id, currentDoc.id)}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            Open in a new tab <ExternalLink />
                          </a>
                        </Button>
                      </div>
                      <iframe
                        key={`${currentDoc.id}-${doc?.page}`}
                        title={currentDoc.name}
                        src={documentUrl(
                          o.id,
                          currentDoc.id,
                          doc?.id === currentDoc.id ? doc.page : null,
                        )}
                        className="min-h-0 w-full flex-1 rounded-md border bg-white"
                      />
                    </div>
                  )}
                </div>
              ) : (
                <Centered>
                  <p className="max-w-md text-center text-muted-foreground">
                    This listing has no readable notice documents attached, so
                    the plan was written from the listing text.{" "}
                    <a
                      className="text-pine underline underline-offset-4"
                      href={o.url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Open the listing
                    </a>{" "}
                    to check for links to the full notice.
                  </p>
                </Centered>
              ))}
          </TabsContent>
        </Tabs>

        {state.status === "done" && (
          <footer className="flex items-center justify-between gap-4 border-t bg-white px-5 py-3 text-[12px] text-muted-foreground sm:px-8 sm:text-[13px]">
            <p className="line-clamp-2 max-w-3xl sm:line-clamp-none">
              {data.documents.length
                ? `AI read ${data.pages_read} of ${data.pages_total} pages from ${data.documents.length} notice document${data.documents.length === 1 ? "" : "s"}`
                : "AI read the listing only (no notice documents)"}
              {data.created_at &&
                ` on ${fmtDate(data.created_at.slice(0, 10))}`}
              . Check every date and requirement against the notice before you
              act.
              {calendarError && <span className="block font-medium text-urgent" role="alert">Couldn't make the calendar file: {calendarError}</span>}
            </p>
            <div className="flex shrink-0 flex-wrap justify-end gap-2">
              <Button
                size="sm"
                variant="blaze"
                onClick={() => { setCalendarError(""); downloadGrantCalendar(agency.id, o.id).catch((e) => setCalendarError(e.message)); }}
                title="Download the deadline and every dated step as an .ics file for Outlook, Google or Apple Calendar"
              >
                <CalendarPlus /> Add timeline to calendar
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => start(true)}
              >
                <RefreshCw /> Run again
              </Button>
            </div>
          </footer>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Centered({ children }) {
  return (
    <div className="flex min-h-[50vh] items-center justify-center p-6">
      {children}
    </div>
  );
}

function Running({ phase, started }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const secs = Math.max(0, Math.round((now - started) / 1000));
  return (
    <Centered>
      <div className="max-w-md" role="status" aria-live="polite">
        <p className="display-light text-4xl text-pine">Reading the notice</p>
        <p className="mt-4 flex items-center gap-2 font-extrabold text-pine">
          <Loader2 className="size-4 shrink-0 animate-spin motion-reduce:[animation-duration:2s]" />{" "}
          {phase}
        </p>
        <p className="mt-1 font-mono text-[12px] text-muted-foreground tabular-nums">
          {secs}s
        </p>
        <p className="mt-5 text-sm text-muted-foreground">
          This usually takes under a minute. You can close this window: the
          research keeps going and will be here when you reopen it.
        </p>
      </div>
    </Centered>
  );
}

function Cite({ source, onCite, className }) {
  if (!source) return null;
  return (
    <button
      type="button"
      onClick={() => onCite(source)}
      className={cn(
        "rounded-sm text-[12.5px] font-medium text-pine-500 underline decoration-pine-300 underline-offset-4 hover:text-pine focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        className,
      )}
    >
      p. {source.page}
    </button>
  );
}

function Section({ title, children }) {
  return (
    <section>
      <h3 className="mb-3 text-sm font-extrabold text-pine">{title}</h3>
      {children}
    </section>
  );
}

function Plan({ data, r, onCite }) {
  const [label, rule] = VERDICT[data.verdict] || VERDICT.unclear;
  const questions = (Array.isArray(data.questions) ? data.questions : [])
    .map((q) => typeof q === "string" ? q : q?.question)
    .filter((q) => typeof q === "string" && q.trim())
    .map((q) => q.trim());
  const steps = [...data.timeline];
  const deadline = data.close_date || r.opportunity.close_date;
  if (deadline && !steps.some((s) => s.date === deadline)) {
    steps.push({
      date: deadline,
      title: "Applications due",
      detail: data.contact?.deadline_note || "The listing's closing date.",
      source: null,
    });
  }
  const contact = data.contact || {};

  return (
    <div className="grid gap-x-12 gap-y-10 px-5 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_300px]">
      <div className="min-w-0">
        <section className={cn("border-l-4 pl-5", rule)}>
          <h3 className="display-light text-[clamp(1.9rem,3.6vw,2.9rem)] leading-[1.05] tracking-[-0.02em] text-pine">
            {label}
          </h3>
          {data.verdict_summary && (
            <p className="mt-3 max-w-[65ch] text-[16px] leading-relaxed">
              {data.verdict_summary}
            </p>
          )}
          {data.eligibility_evidence.length > 0 && (
            <ul className="mt-4 flex max-w-[65ch] flex-col gap-3">
              {data.eligibility_evidence.map((e, i) => (
                <li key={i} className="text-[14.5px]">
                  <blockquote className="font-display text-[16px] leading-relaxed text-pine-ink/85 italic">
                    “{e.quote}”
                  </blockquote>
                  <span className="text-[12.5px] text-muted-foreground">
                    {e.doc_name},{" "}
                  </span>
                  <Cite source={e} onCite={onCite} />
                </li>
              ))}
            </ul>
          )}
          {data.unverified_quotes > 0 && (
            <p className="mt-3 text-[12.5px] text-muted-foreground">
              {data.unverified_quotes} quote
              {data.unverified_quotes === 1 ? "" : "s"} from the AI couldn't be
              found word for word in the notice, so{" "}
              {data.unverified_quotes === 1 ? "it was" : "they were"} left out.
            </p>
          )}
        </section>

        {data.fit && (
          <p className="mt-6 max-w-[65ch] text-[15px] text-muted-foreground">
            {data.fit}
          </p>
        )}

        <section className="mt-12">
          <h3 className="mb-6 text-sm font-extrabold text-pine">
            Timeline to submission
          </h3>
          <Trail steps={steps} onCite={onCite} />
        </section>
      </div>

      <aside className="flex flex-col gap-9 lg:border-l lg:pl-8">
        {data.key_dates.length > 0 && (
          <Section title="Key dates">
            <dl className="flex flex-col gap-2.5 text-[14px]">
              {data.key_dates.map((k, i) => (
                <div key={i}>
                  <dt className="font-extrabold text-pine">
                    {k.date ? fmtDate(k.date) : "Date not given"}
                  </dt>
                  <dd>
                    {k.label} <Cite source={k.source} onCite={onCite} />
                  </dd>
                </div>
              ))}
            </dl>
          </Section>
        )}
        {data.requirements.length > 0 && (
          <Section title="What the application needs">
            <ul className="flex flex-col gap-3 text-[14px]">
              {data.requirements.map((q, i) => (
                <li key={i} className="border-l-2 border-pine-300 pl-3">
                  <p className="font-extrabold">{q.item}</p>
                  {q.detail && (
                    <p className="text-muted-foreground">
                      {q.detail} <Cite source={q.source} onCite={onCite} />
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </Section>
        )}
        {questions.length > 0 && (
          <Section title="Ask the program officer">
            <ul className="flex list-disc flex-col gap-2 pl-4 text-[14px] marker:text-blaze">
              {questions.map((q, i) => (
                <li key={i}>{q}</li>
              ))}
            </ul>
          </Section>
        )}
        {(contact.email || contact.phone) && (
          <Section title="Program contact">
            <div className="flex flex-col gap-1.5 text-[14px]">
              {contact.name && <p className="font-extrabold">{contact.name}</p>}
              {contact.email && (
                <a
                  className="flex items-center gap-2 text-pine underline-offset-4 hover:underline"
                  href={`mailto:${contact.email}`}
                >
                  <Mail className="size-4" />
                  {contact.email}
                </a>
              )}
              {contact.phone && (
                <a
                  className="flex items-center gap-2 text-pine underline-offset-4 hover:underline"
                  href={`tel:${contact.phone}`}
                >
                  <Phone className="size-4" />
                  {contact.phone}
                </a>
              )}
            </div>
          </Section>
        )}
      </aside>
    </div>
  );
}

/** The timeline as a trail: honey blazes mark each step, and the deadline is the summit. */
function Trail({ steps, onCite }) {
  return (
    <motion.ol
      className="relative"
      initial="hidden"
      animate="show"
      variants={{
        show: { transition: { staggerChildren: 0.08, delayChildren: 0.25 } },
      }}
    >
      <motion.span
        aria-hidden="true"
        className="absolute top-2 bottom-6 left-[87px] w-0.5 origin-top bg-pine-300 sm:left-[103px]"
        variants={{
          hidden: { scaleY: 0 },
          show: {
            scaleY: 1,
            transition: { duration: 0.9, ease: [0.3, 0.6, 0.2, 1] },
          },
        }}
      />
      {steps.map((s, i) => {
        const last = i === steps.length - 1;
        const d = shortDate(s.date);
        return (
          <motion.li
            key={i}
            className="relative grid grid-cols-[72px_32px_minmax(0,1fr)] gap-x-2 pb-8 sm:grid-cols-[88px_32px_minmax(0,1fr)]"
            variants={{
              hidden: { opacity: 0, x: -8 },
              show: { opacity: 1, x: 0, transition: { duration: 0.4 } },
            }}
          >
            <div className="pt-0.5 text-right">
              {d ? (
                <>
                  <p
                    className={cn(
                      "leading-tight font-extrabold",
                      last ? "text-pine" : "text-pine-ink",
                    )}
                  >
                    {d.day}
                  </p>
                  <p className="text-[12px] text-muted-foreground">{d.rest}</p>
                </>
              ) : (
                <p className="text-[12.5px] text-muted-foreground">No date</p>
              )}
            </div>
            <div className="flex justify-center pt-1">
              {last ? (
                <span
                  className="size-4 rotate-45 bg-pine ring-4 ring-fog"
                  aria-hidden="true"
                />
              ) : (
                <span
                  className="h-4 w-2.5 rounded-[1px] bg-blaze ring-4 ring-fog"
                  aria-hidden="true"
                />
              )}
            </div>
            <div className="min-w-0">
              <p
                className={cn(
                  "text-[16px] leading-snug font-extrabold",
                  last && "text-pine",
                )}
              >
                {s.title}
              </p>
              {s.detail && (
                <p className="mt-1 max-w-[60ch] text-[14.5px] text-muted-foreground">
                  {s.detail} <Cite source={s.source} onCite={onCite} />
                </p>
              )}
            </div>
          </motion.li>
        );
      })}
    </motion.ol>
  );
}
