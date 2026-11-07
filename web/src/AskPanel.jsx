import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, ArrowUp, FileText, Loader2, X } from "lucide-react";
import { api, documentUrl } from "./api.js";
import { BridgeMark } from "./AgencyPicker.jsx";
import ContourField from "./ContourField.jsx";
import Explained, { GlossaryContext } from "./Explained.jsx";
import { buildGlossary } from "./grantTerms.js";
import { TrailLoader } from "./StateSurvey.jsx";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const STARTERS = [
  "Can a state agency like mine apply?",
  "Is there a cost share, and how much?",
  "What's the page limit for the narrative?",
  "What costs aren't allowed?",
  "Are there deadlines before the due date?",
];
const HISTORY_TURNS = 6;

/** How GrantBot introduces itself: on hover, and as its first message. One wording everywhere. */
export const GRANTBOT_HELLO = "Hi, I'm GrantBot.";
export const GRANTBOT_HELPS =
  "I can help you with this grant: who can apply, the cost share, deadlines, page limits, and what the money can pay for. " +
  "I answer only from the notice documents and the listing, and I show you the page each answer came from.";

/** GrantBot's face: the GrantNC bridge. */
export function GrantBotAvatar({ className }) {
  return (
    <span aria-hidden="true" className={cn("grid size-8 shrink-0 place-items-center rounded-full bg-white ring-1 ring-border", className)}>
      <BridgeMark className="size-6 rounded-sm" />
    </span>
  );
}

function FromGrantBot({ children }) {
  return (
    <div className="flex max-w-[92%] items-start gap-2.5">
      <GrantBotAvatar className="mt-5" />
      <div className="min-w-0">
        <p className="mb-1 text-[12px] font-extrabold text-pine">GrantBot</p>
        {children}
      </div>
    </div>
  );
}

/** Questions and answers about one grant, from its notice documents. `onCite` opens a cited page;
    without it, citations open the PDF in a new tab. Nothing is saved: closing the page clears it. */
export default function AskPanel({ opportunity: o, agency, onCite, className }) {
  const [turns, setTurns] = useState([]); // { role, content, found?, citations?, follow_ups?, error? }
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);
  const inputRef = useRef(null);
  const outer = useContext(GlossaryContext);
  const glossary = useMemo(() => outer || buildGlossary([]), [outer]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns, busy]);

  // `before` replaces the conversation so far (a retry drops the failed question and its error first).
  const send = async (question, before = turns) => {
    const q = question.trim();
    if (q.length < 3 || busy) return;
    const history = before.filter((t) => !t.error).slice(-HISTORY_TURNS).map(({ role, content }) => ({ role, content }));
    setTurns([...before, { role: "user", content: q }]);
    setDraft("");
    setBusy(true);
    try {
      const res = await api.ask({ opportunity_id: o.id, agency_id: agency.id, question: q, history });
      setTurns((t) => [...t, { role: "assistant", content: res.answer, found: res.found, citations: res.citations, follow_ups: res.follow_ups }]);
    } catch (e) {
      setTurns((t) => [...t, { role: "assistant", content: e.message, error: true, retry: q }]);
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  };

  const openCite = (c) => (onCite ? onCite(c) : window.open(documentUrl(o.id, c.doc_id, c.page), "_blank", "noopener"));
  const lastAnswer = [...turns].reverse().find((t) => t.role === "assistant" && !t.error);

  return (
    <GlossaryContext.Provider value={glossary}>
      <div className={cn("flex min-h-0 flex-1 flex-col", className)}>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-6 sm:px-8" role="log" aria-live="polite" aria-label="Questions and answers">
          {(
            <ol className="mx-auto flex max-w-3xl flex-col gap-5">
              <li className="flex justify-start">
                <FromGrantBot>
                  <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}
                    className="rounded-2xl rounded-tl-sm border bg-white px-4 py-3 shadow-xs">
                    <p className="font-display text-[22px] leading-tight font-extrabold tracking-[-0.01em] text-pine">{GRANTBOT_HELLO}</p>
                    <p className="mt-1.5 text-[15px] leading-relaxed">{GRANTBOT_HELPS}</p>
                  </motion.div>
                </FromGrantBot>
              </li>
              {turns.length === 0 && (
                <li className="flex flex-wrap gap-2 pl-[42px]">
                  {STARTERS.map((q) => (
                    <Button key={q} variant="outline" size="sm" className="h-auto rounded-full bg-white px-3.5 py-1.5 text-left text-[13.5px] whitespace-normal"
                      onClick={() => send(q)}>{q}</Button>
                  ))}
                </li>
              )}
              <AnimatePresence initial={false}>
                {turns.map((t, i) => (
                  <motion.li key={i} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}
                    className={cn("flex", t.role === "user" ? "justify-end" : "justify-start")}>
                    {t.role === "user" ? (
                      <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-pine px-4 py-2.5 text-[15px] text-fog">{t.content}</p>
                    ) : t.error ? (
                      <FromGrantBot><div className="rounded-2xl rounded-tl-sm border border-urgent/30 bg-urgent-bg px-4 py-3 text-[14.5px]">
                        <p className="flex items-start gap-2 text-urgent"><AlertTriangle className="mt-0.5 size-4 shrink-0" /> {t.content}</p>
                        {i === turns.length - 1 && (
                          <Button size="sm" variant="outline" className="mt-2 bg-white" disabled={busy}
                            onClick={() => send(t.retry, turns.slice(0, -2))}>Try again</Button>
                        )}
                      </div></FromGrantBot>
                    ) : (
                      <FromGrantBot><Answer turn={t} onCite={openCite} /></FromGrantBot>
                    )}
                  </motion.li>
                ))}
              </AnimatePresence>
              {busy && (
                <li className="flex items-center gap-2.5 text-[14px] text-muted-foreground" role="status">
                  <GrantBotAvatar />
                  <TrailLoader />
                  GrantBot is reading the notice{turns.length <= 1 ? ". The first question can take up to a minute while the documents download." : "…"}
                </li>
              )}
              {!busy && lastAnswer?.follow_ups?.length > 0 && turns.at(-1) === lastAnswer && (
                <li className="flex flex-wrap gap-2 pl-[42px]">
                  {lastAnswer.follow_ups.map((q) => (
                    <Button key={q} variant="outline" size="sm" className="h-auto rounded-full bg-white px-3 py-1 text-left text-[13px] whitespace-normal"
                      onClick={() => send(q)}>{q}</Button>
                  ))}
                </li>
              )}
              <li ref={endRef} aria-hidden="true" />
            </ol>
          )}
        </div>

        <form className="border-t bg-white px-5 py-3 sm:px-8" onSubmit={(e) => { e.preventDefault(); send(draft); }}>
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            <label htmlFor={`ask-${o.id}`} className="sr-only">Your question</label>
            <Textarea id={`ask-${o.id}`} ref={inputRef} value={draft} maxLength={1000} rows={1}
              placeholder="Ask GrantBot about this grant"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(draft); } }}
              className="max-h-40 min-h-11 resize-none bg-white text-[15px]" />
            <Button type="submit" size="icon" className="size-11 shrink-0" disabled={busy || draft.trim().length < 3} aria-label="Send to GrantBot">
              {busy ? <Loader2 className="animate-spin" /> : <ArrowUp />}
            </Button>
          </div>
          <p className="mx-auto mt-2 max-w-3xl text-[12px] text-muted-foreground">
            AI answers from the notice; check the cited page before relying on one. Conversations aren't saved.
          </p>
        </form>
      </div>
    </GlossaryContext.Provider>
  );
}

function Answer({ turn: t, onCite }) {
  return (
    <div className="rounded-2xl rounded-tl-sm border bg-white px-4 py-3 shadow-xs">
      {!t.found && <Badge className="mb-2 bg-blaze-tint text-[11px] text-blaze-deep">Not in the notice</Badge>}
      <p className="text-[15px] leading-relaxed whitespace-pre-line"><Explained text={t.content} /></p>
      {t.citations?.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2 border-t pt-2.5">
          {t.citations.map((c) => (
            <li key={`${c.doc_id}-${c.page}`} className="text-[13px]">
              <button type="button" onClick={() => onCite(c)}
                className="inline-flex items-center gap-1 rounded-sm font-medium text-pine-500 underline decoration-pine-300 underline-offset-4 hover:text-pine focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
                <FileText className="size-3.5" /> {c.doc_name}, p. {c.page}
              </button>
              {c.verified ? (
                <q className="mt-0.5 block font-display text-[14px] text-pine-ink/80 italic">{c.quote}</q>
              ) : (
                <span className="ml-1 text-muted-foreground">(the quoted words weren't found on this page; check it)</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The chat on its own, from a grant card: no research run needed. */
export function AskDialog({ open, onOpenChange, opportunity: o, agency }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false} className="flex h-[min(88vh,860px)] flex-col gap-0 overflow-hidden bg-fog p-0 sm:max-w-4xl">
        <header className="topo-sky relative isolate overflow-hidden px-5 py-5 text-fog sm:px-8">
          <ContourField className="-z-10 opacity-30" />
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <DialogDescription className="flex items-center gap-2 text-[13px] text-fog/75">
                <GrantBotAvatar className="size-6" /> GrantBot, for {agency.name}
              </DialogDescription>
              <DialogTitle className="mt-1 text-xl leading-snug font-extrabold tracking-[-0.01em]">{o.title}</DialogTitle>
            </div>
            <DialogClose asChild>
              <Button variant="ghost" size="icon" className="shrink-0 text-fog hover:bg-fog/10 hover:text-fog" aria-label="Close"><X /></Button>
            </DialogClose>
          </div>
        </header>
        <AskPanel opportunity={o} agency={agency} />
      </DialogContent>
    </Dialog>
  );
}
