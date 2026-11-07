# Frontend aesthetics

Avoid generic AI aesthetics. Make creative, distinctive choices.

## Typography

- Never use Inter, Roboto, Open Sans, Lato, Arial, or system fonts.
- Body: Bricolage Grotesque. Display: Fraunces. Mono: JetBrains Mono.
- Use weight extremes: 200 vs 800, not 400 vs 600.
- Size jumps of 3x+, not 1.5x.

## Color & theme

- Commit to a single dominant color with one sharp accent.
- All colors live in CSS variables in `app/globals.css`.
- Forbidden: purple-to-blue gradients on white backgrounds.

## Backgrounds

- Layered CSS gradients or geometric patterns over solid colors.
- Hero sections must have atmospheric depth.

## Motion

- CSS-only for non-React. Motion (formerly Framer Motion) for React.
- One well-orchestrated page-load reveal beats scattered micro-interactions.

## Components

- Always use shadcn/ui primitives where they exist (Button, Card, Dialog, Form).
- Never hand-roll a component that exists in the shadcn registry.
- Tailwind classes only. No inline styles. No CSS modules.
