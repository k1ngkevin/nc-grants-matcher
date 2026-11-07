import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

const TIMING_HELP = {
  urgent: "Act now. Decide quickly whether to apply.",
  standard: "Enough time to prepare a strong application.",
  later: "Plenty of runway. Good for planning.",
  forecasted: "The agency has announced it's coming but it isn't open yet. Start lining up partners and match.",
};

function Section({ title, children }) {
  return (
    <section>
      <h3 className="mb-1 text-sm font-extrabold text-pine">{title}</h3>
      {children}
    </section>
  );
}

function Terms({ entries }) {
  return (
    <dl className="divide-y text-sm">
      {entries.map(([term, def]) => (
        <div key={term} className="grid gap-1 py-2 sm:grid-cols-[170px_1fr] sm:gap-3">
          <dt className="font-medium">{term}</dt>
          <dd className="text-muted-foreground">{def}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function Glossary({ meta, open, onOpenChange }) {
  const g = meta.glossary;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="display-light text-3xl font-extralight text-pine">Grant types in plain English</DialogTitle>
          <DialogDescription>What the labels on each grant mean, and how the match score is worked out.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-5">
          <Section title="How awards are decided">
            <Terms entries={Object.entries(g.competition)} />
          </Section>
          <Section title="Type of funding">
            <Terms entries={[
              ...Object.entries(g.instruments),
              ["Matching funds (cost share)", "Your agency must contribute some of the project cost, in cash or in-kind, alongside the federal money."],
            ]} />
          </Section>
          <Section title="Deadlines">
            <Terms entries={Object.entries(g.timing).map(([k, v]) => [v, TIMING_HELP[k]])} />
          </Section>
          <Section title="How the match score works">
            <p className="text-sm text-muted-foreground">
              Out of 100: fit with your mission and active projects ({meta.weights.semantic}), whether it's a federal program your agency usually receives plus key topics ({meta.weights.program}),
              eligibility ({meta.weights.eligibility}), timing ({meta.weights.timing}) and award size ({meta.weights.size}). Formula / mandatory grants get +8 because they usually go to every eligible state; continuations get −15 because
              they're usually open only to current grantees; earmarks directed to another recipient are hidden.
              Your team's Pursue, Save and Dismiss decisions nudge future scores.
              {" "}Good and Strong labels also require enough mission/project similarity and combined mission and program relevance.
              {" "}The preview separates mission and program relevance from practical factors. AI summaries explain the breakdown and flag gaps in the listing.
              The score helps prioritize review. People make the decisions.
            </p>
          </Section>
          <Section title="Where the data comes from">
            <p className="text-sm text-muted-foreground">
              Open opportunities from Grants.gov (refreshed daily), program descriptions from SAM.gov Assistance Listings, and past NC awards from USAspending.gov.
              {" "}Matching uses {meta.ai.embeddings === "azure" ? "Azure OpenAI embeddings" : "local text similarity"}; explanations are {meta.ai.explanations === "rules" ? "rule-based" : "AI-written and grounded in the listing"}.
            </p>
          </Section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
