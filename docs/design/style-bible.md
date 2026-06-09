# OpenHealth Style Bible

**Status:** draft · **Date:** 2026-05-30

An original visual language for OpenHealth, informed by editorial,
number-forward product design (warm-canvas and dark widget-board directions).
This is a synthesis of *principles*, not a copy of any one designer's screens.
It supersedes the earlier "calm clinical" defaults where they conflict.

## 1. Two surfaces, one system

- **Light — Editorial Canvas.** Warm off-white ground, near-black ink, one
  saturated accent, muted cards. Generous margins; the screen breathes.
- **Dark — Widget Board.** Near-black ground, glassy tiles with soft mesh
  gradients, luminous numbers. Same type scale and spacing, inverted values.

Both are **number-forward**: the most important value on a screen is the largest
thing on it.

## 2. Color

Semantic colors are fixed and never decorative:
- `inRange / primary` teal `#1F8A7A`
- `attention` amber `#C77D2E`
- `critical / safety` red `#C0392B` — **only** safety. Never decorative.

Canvas + ink:
- Light ground `#F4F1EA` (warm), ink `#16181C`, soft ink `#6B7178`, hairline `#E7E3D9`
- Dark ground `#0E0F12`, ink `#F4F2EC`, soft `#9AA0A8`, tile `#171A1F`

Decorative gradients (hero rings, tiles) are calm and metric-keyed, drawn from a
restrained set — teal→mint, slate→periwinkle, clay→sand, plum→mauve. Gradients
carry no clinical meaning; flags always use the semantic colors above.

Rule: at most one saturated accent visible per screen region. Muted neutrals do
the structural work; color is punctuation.

## 3. Typography

A two-voice system:
- **Display / editorial** — a serif or a heavy grotesk for greetings, section
  openers, and big statements. Tight leading, mixed weight within a line
  (key words heavy, the rest quiet) for editorial rhythm.
- **Numeric hero** — rounded, **tabular** figures, oversized. Integer part bold;
  decimals/units stepped down in size and softened. The number is the artwork.
- **Functional** — system sans for labels, captions, body. UPPERCASE micro-labels
  with positive tracking for tile/section headers.

Scale (pt): 40 display · 30 section · 22 title · 17 body · 15 secondary ·
13 caption · 11 micro-label. Numbers can go 48–72 as hero.

## 4. Layout & components

- **Editorial annotations.** Small index tags, dividers and micro-labels frame
  content like a portfolio page — `{02}`, section rules, unit chips.
- **Cards / tiles.** Large continuous-corner radius (18–24), 1px warm hairline in
  light, soft fill in dark. Varied tile sizes form a board: one hero, then a
  mosaic.
- **Ring as hero.** A single colored ring with the value centered, plus one
  plain-language readout line beneath. Recovery/score lives here.
- **Bottom nav.** Compact, rounded, glassy; active item in the accent. Never more
  than 4 destinations.

## 5. Motion (nuance, not noise)

- Numbers **count up** on appear (200–400ms, ease-out). Rings **draw** from 0 to
  value once.
- Cards rise with a small (8–12pt) fade-and-translate, staggered ~40ms.
- Navigation: matched-geometry transition for the hero (tile → detail).
- Everything is calm and brief; respects Reduce Motion.

## 6. Voice on screen

Honest and quiet. Confidence is always visible (C1–C5 chips that fade as
certainty drops). Findings at C3 and below are phrased as questions. Safety
banners are the only loud element, and the only place red appears.

> Craft details that matter: optical alignment of big numbers, consistent
> hairlines, tabular figures everywhere, true continuous corners, and never a
> bare number without a one-line "what this means".
