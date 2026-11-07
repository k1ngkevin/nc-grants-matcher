import { motion, useReducedMotion } from "motion/react";
import NC from "./ncSurvey.json";
import { cn } from "@/lib/utils";

const EASE = [0.3, 0.6, 0.2, 1];
// The survey runs west to east, the way the state rises out of the Blue Ridge and runs down to the Outer Banks.
const sweep = (x) => 0.5 + (x / NC.width) * 1.4;
const TRACE_AT = 1.1;    // the blaze-yellow state line starts once the first counties are down
const ARRIVE_AT = 3.1;   // Raleigh's blaze lands after the line closes

/** North Carolina as a surveyor's sheet: 100 county lines, the state line in trail-blaze yellow, and a blaze
    on Raleigh, where the agencies using this tool are based. With `draw`, it surveys itself once on mount. */
export default function StateSurvey({ draw = false, labels = true, className }) {
  const reduce = useReducedMotion();
  const animate = draw && !reduce;
  const [rx, ry] = NC.raleigh;
  const at = (delay, rest = {}) => (animate ? { delay, ...rest } : { duration: 0 });

  return (
    <svg viewBox={`0 0 ${NC.width} ${NC.height}`} aria-hidden="true" preserveAspectRatio="xMidYMid meet"
      className={cn("pointer-events-none overflow-visible fill-none", className)}>
      <motion.path d={NC.outline} className="fill-fog/[0.035]"
        initial={animate ? { opacity: 0 } : false} animate={{ opacity: 1 }} transition={at(TRACE_AT + 1.2, { duration: 1.4 })} />

      {NC.counties.map((c, i) => (
        <motion.path key={i} d={c.d} vectorEffect="non-scaling-stroke" strokeLinejoin="round"
          className="stroke-fog/20 stroke-[0.7]"
          initial={animate ? { pathLength: 0, opacity: 0 } : false}
          animate={{ pathLength: 1, opacity: 1 }}
          transition={at(sweep(c.x), { duration: 1.2, ease: EASE })} />
      ))}

      <motion.path d={NC.outline} vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round"
        className="stroke-blaze/85 stroke-[1.6]"
        initial={animate ? { pathLength: 0 } : false} animate={{ pathLength: 1 }}
        transition={at(TRACE_AT, { duration: 2.1, ease: [0.45, 0, 0.2, 1] })} />

      {labels && NC.regions.map((r, i) => (
        <motion.text key={r.name} x={r.at[0]} y={r.at[1]} textAnchor="middle"
          className="fill-fog/60 font-display text-[23px] font-extralight italic tracking-[0.02em]"
          initial={animate ? { opacity: 0 } : false} animate={{ opacity: 1 }}
          transition={at(2.3 + i * 0.18, { duration: 0.9, ease: EASE })}>
          {r.name}
        </motion.text>
      ))}

      {/* Raleigh: a painted trail blaze, with one ring spreading out as it lands. */}
      <g transform={`translate(${rx} ${ry})`}>
        {animate && (
          <motion.circle r={20} className="stroke-blaze stroke-[1.2]" vectorEffect="non-scaling-stroke"
            initial={{ scale: 0.2, opacity: 0 }} animate={{ scale: [0.2, 1.6], opacity: [0.9, 0] }}
            transition={{ delay: ARRIVE_AT + 0.15, duration: 1.4, ease: "easeOut", repeat: 1, repeatDelay: 0.4 }} />
        )}
        <motion.rect x={-4.5} y={-8} width={9} height={16} rx={1.5} className="fill-blaze"
          initial={animate ? { scale: 0, opacity: 0 } : false} animate={{ scale: 1, opacity: 1 }}
          transition={at(ARRIVE_AT, { type: "spring", stiffness: 420, damping: 18 })} />
        {labels && (
          <motion.text x={14} y={7} className="fill-fog font-display text-[22px] font-extrabold"
            initial={animate ? { opacity: 0 } : false} animate={{ opacity: 1 }}
            transition={at(ARRIVE_AT + 0.25, { duration: 0.6, ease: EASE })}>
            Raleigh
          </motion.text>
        )}
      </g>
    </svg>
  );
}

/** Three trail blazes marked one after another, like markers coming into view on a trail. For waits. */
export function TrailLoader({ className, tone = "pine" }) {
  return (
    <span role="presentation" className={cn("inline-flex items-end gap-[3px]", className)}>
      {[0, 1, 2].map((i) => (
        <span key={i}
          className={cn("h-3.5 w-[6px] rounded-[1.5px] animate-[blaze-step_1.5s_ease-in-out_infinite] motion-reduce:animate-none",
            tone === "fog" ? "bg-blaze" : "bg-blaze-deep", i === 1 && "[animation-delay:0.25s]", i === 2 && "[animation-delay:0.5s]")} />
      ))}
    </span>
  );
}
