import { motion, useReducedMotion } from "motion/react";
import { CONTOURS, CONTOUR_LEVELS } from "./contours.js";
import { cn } from "@/lib/utils";

// Like a USGS map: every fifth line is a heavier "index" contour, and the summits are marked in the accent.
function strokeClass(level) {
  const summit = level >= CONTOUR_LEVELS - 3;
  const index = level % 5 === 4;
  return cn(
    index ? "stroke-[1.6]" : "stroke-[0.9]",
    summit ? "stroke-blaze/80" : level >= 10 ? "stroke-fog/30" : level >= 5 ? "stroke-fog/20" : "stroke-fog/12",
  );
}

/** Topographic contours of a synthetic Blue Ridge (ridges run SW to NE, as they do across NC).
    With `draw`, the terrain draws itself from the valleys up, once, on mount. */
export default function ContourField({ draw = false, className }) {
  const reduce = useReducedMotion();
  const animate = draw && !reduce;
  return (
    <svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true"
      className={cn("pointer-events-none absolute inset-0 size-full fill-none", className)}>
      {CONTOURS.map((c, i) =>
        animate ? (
          <motion.path key={i} d={c.d} vectorEffect="non-scaling-stroke" strokeLinecap="round" className={strokeClass(c.l)}
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ duration: 1.9, delay: 0.1 + c.l * 0.05, ease: [0.3, 0.6, 0.2, 1] }} />
        ) : (
          <path key={i} d={c.d} vectorEffect="non-scaling-stroke" strokeLinecap="round" className={strokeClass(c.l)} />
        )
      )}
    </svg>
  );
}
