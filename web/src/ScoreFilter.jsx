import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const SCORE_OPTIONS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100];

export default function ScoreFilter({ filters, onChange, belowScoreCount }) {
  // Keep a previously saved custom threshold selectable, too.
  const options = [...new Set([...SCORE_OPTIONS, filters.min_score])].sort((a, b) => a - b);
  const includeLower = filters.include_lower_scores;
  const hasLowerScores = belowScoreCount > 0;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="min-score" className="text-sm font-normal text-muted-foreground">Minimum score</Label>
          <Select value={String(filters.min_score)} onValueChange={(value) => onChange({ ...filters, min_score: Number(value) })}>
            <SelectTrigger id="min-score" size="sm" className="w-24 bg-white"><SelectValue /></SelectTrigger>
            <SelectContent>
              {options.map((score) => <SelectItem key={score} value={String(score)}>{score}+</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox id="include-lower-scores" checked={includeLower}
            onCheckedChange={(checked) => onChange({ ...filters, include_lower_scores: checked === true })}
            aria-describedby="score-filter-status" />
          <Label htmlFor="include-lower-scores" className="cursor-pointer text-sm font-normal">Include lower scores</Label>
        </div>
      </div>
      <p id="score-filter-status" aria-live="polite" className="mt-1.5 text-[13px] text-muted-foreground">
        {includeLower ? "Showing all scores." : `Showing scores ${filters.min_score} and above.`}
        {hasLowerScores && (includeLower
          ? ` Includes ${belowScoreCount} below ${filters.min_score}.`
          : ` ${belowScoreCount} lower-scoring ${belowScoreCount === 1 ? "grant is" : "grants are"} hidden.`)}
      </p>
    </div>
  );
}
