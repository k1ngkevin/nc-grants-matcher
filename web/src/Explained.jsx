import { createContext, useContext } from "react";
import { findTerms } from "./grantTerms.js";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/** The glossary for the report on screen: built-in grant terms plus the notice's own. */
export const GlossaryContext = createContext(null);

/** Text with jargon marked: a dotted underline, and the plain-English meaning on hover or keyboard focus. */
export default function Explained({ text }) {
  const glossary = useContext(GlossaryContext);
  if (!text || !glossary) return text || null;
  return findTerms(text, glossary).map((piece, i) =>
    piece.entry ? (
      <Tooltip key={i}>
        <TooltipTrigger asChild>
          <span tabIndex={0}
            className="cursor-help rounded-sm underline decoration-pine-300 decoration-dotted decoration-2 underline-offset-4 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
            {piece.text}
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs text-[12.5px] leading-snug">
          <span className="block font-extrabold">{piece.entry.term}</span>
          {piece.entry.meaning}
        </TooltipContent>
      </Tooltip>
    ) : (
      <span key={i}>{piece.text}</span>
    ),
  );
}
