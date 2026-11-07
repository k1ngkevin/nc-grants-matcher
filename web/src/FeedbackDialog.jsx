import { useEffect, useState } from "react";
import { CheckCircle2 } from "lucide-react";
import { api, store } from "./api.js";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const KINDS = [
  ["problem", "Something's wrong", "An error, or something that doesn't work", "What happened, and what did you expect?"],
  ["scoring", "Score looks off", "A grant ranked too high or too low", "Which grant, and why does the score seem wrong?"],
  ["idea", "Idea", "Something that would help your team", "What would make this more useful?"],
  ["other", "Other", "Anything else", "What's on your mind?"],
];

/** Feedback to the team that runs the site. Opened from the header, or from a grant (which attaches it). */
export default function FeedbackDialog({ open, onOpenChange, agency, opportunity, initialKind = "problem", page }) {
  const [kind, setKind] = useState(initialKind);
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState(() => store.get("email", ""));
  const [state, setState] = useState({ status: "idle" });

  useEffect(() => {
    if (open) {
      setKind(initialKind);
      setState({ status: "idle" });
    }
  }, [open, initialKind, opportunity?.id]);

  const submit = async (e) => {
    e.preventDefault();
    setState({ status: "busy" });
    try {
      await api.sendFeedback({
        kind, message: message.trim(), email: email.trim(),
        agency_id: agency?.id || "", opportunity_id: opportunity?.id || "", page: page || "",
      });
      if (email.trim()) store.set("email", email.trim());
      setMessage("");
      setState({ status: "done" });
    } catch (err) {
      setState({ status: "error", error: err.message });
    }
  };

  const placeholder = KINDS.find(([k]) => k === kind)?.[3];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="display-light text-3xl font-extralight text-pine">Send feedback</DialogTitle>
          <DialogDescription>It goes to the team that runs this site. We read every message.</DialogDescription>
        </DialogHeader>

        {state.status === "done" ? (
          <div className="flex flex-col items-start gap-4 py-2" role="status">
            <p className="flex items-center gap-2 text-lg font-extrabold text-pine"><CheckCircle2 className="size-5" /> Thanks. Your feedback was sent.</p>
            <p className="text-sm text-muted-foreground">
              {email.trim() ? `If we have questions, we'll reply to ${email.trim()}.` : "You didn't leave an email, so we won't be able to reply."}
            </p>
            <div className="flex gap-2">
              <Button onClick={() => onOpenChange(false)}>Close</Button>
              <Button variant="outline" onClick={() => setState({ status: "idle" })}>Send more</Button>
            </div>
          </div>
        ) : (
          <form className="flex flex-col gap-5" onSubmit={submit}>
            <fieldset>
              <legend className="mb-2 text-sm font-extrabold">What kind of feedback?</legend>
              <RadioGroup value={kind} onValueChange={setKind} className="grid gap-2 sm:grid-cols-2">
                {KINDS.map(([key, label, hint]) => (
                  <Label key={key} htmlFor={`fb-${key}`}
                    className={cn("flex cursor-pointer items-start gap-3 rounded-md border bg-white p-3 font-normal transition-colors motion-reduce:transition-none",
                      kind === key ? "border-pine ring-1 ring-pine" : "hover:border-pine-300")}>
                    <RadioGroupItem id={`fb-${key}`} value={key} className="mt-0.5" />
                    <span className="flex flex-col gap-0.5">
                      <span className="font-extrabold text-pine-ink">{label}</span>
                      <span className="text-[13px] text-muted-foreground">{hint}</span>
                    </span>
                  </Label>
                ))}
              </RadioGroup>
            </fieldset>

            <div>
              <Label htmlFor="fb-message" className="mb-1.5 text-sm font-extrabold">Your message</Label>
              <Textarea id="fb-message" rows={5} required minLength={5} maxLength={4000} placeholder={placeholder}
                value={message} onChange={(e) => setMessage(e.target.value)} className="bg-white" />
            </div>

            <div>
              <Label htmlFor="fb-email" className="mb-1.5 text-sm font-extrabold">
                Your email <span className="font-normal text-muted-foreground">(optional, if you'd like a reply)</span>
              </Label>
              <Input id="fb-email" type="email" placeholder="you@agency.nc.gov" value={email} onChange={(e) => setEmail(e.target.value)} className="bg-white" />
            </div>

            {(agency || opportunity) && (
              <p className="text-[13px] text-muted-foreground">
                Sent with {[agency?.name, opportunity && `the grant "${opportunity.title}"`].filter(Boolean).join(" and ")}, so we can see what you saw.
              </p>
            )}

            {state.status === "error" && (
              <Alert variant="destructive" className="bg-urgent-bg py-2"><AlertDescription>{state.error}</AlertDescription></Alert>
            )}

            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
              <Button type="submit" disabled={state.status === "busy" || message.trim().length < 5}>
                {state.status === "busy" ? "Sending…" : "Send feedback"}
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
