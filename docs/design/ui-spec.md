# UI Specification (desktop + mobile)

**Status:** draft for community review
**Date:** 2026-05-29

A design spec for the OpenHealth dashboard, grounded in real shipped patterns
from premium health apps (references via Mobbin). The UI is a thin local-first
view over the Python engine; it never invents data and always renders the
engine's confidence and safety signals (see
[evidence-and-trust.md](../methodology/evidence-and-trust.md)).

Audience is **beginners**. The bar: a first-time user understands their screen in
under 10 seconds and is never shown a scary number without calm, sourced context.

## Reference patterns (what we borrow and why)

| Pattern | Reference app | Mobbin | What we take |
|---------|---------------|--------|--------------|
| Daily overview with rings + plain-language insight card | Bevel | https://mobbin.com/screens/11e305e4-bcad-4180-92dc-73383e2accdc | Strain/Recovery/Sleep rings + a one-paragraph "what this means" card |
| Warm home: "Good morning" + missions + latest measurements | Withings Health Mate | https://mobbin.com/screens/6d692992-1c7c-4c7d-8b8b-53727f300aa9 | Personal greeting, today's small actions, latest values list |
| In/out of range chart + "Learn more why this matters" | Fitbit (Blood Glucose) | https://mobbin.com/screens/1ea38902-fde2-41b1-b735-874d399e9971 | Green "in range" bar, explicit out-of-range marker, learn-more link |
| Cautious result explainer with physician disclaimer | Noom | https://mobbin.com/screens/9628042d-3bf1-4420-8688-e1789725ac6e | "Your result is X, in the normal range. Diagnosis should be made by a physician." |
| Trends with timeframe toggle + streak | Cal AI | https://mobbin.com/screens/1c2836f3-bfa9-4d62-bb0b-1ff046f42dd7 | 90d/6m/1y toggle, goal-progress line, encouraging copy |

## Information architecture

**Mobile (primary, 4-tab bar):**
1. **Today** — greeting, today's check-in prompt, latest measurements, any open
   review prompts (out-of-range / red flags pinned to top).
2. **Trends** — pick a signal (sleep, a lab marker, weight…), timeframe toggle,
   line chart with reference band shaded, plain-language read-out.
3. **Records** — sources list (WHOOP, lab panels, notes, photos); tap a lab panel
   to see the marker detail screen.
4. **Insights** — hypothesis cards (engine-derived + pulled community templates),
   each with a C1–C5 label and a "test this" n-of-1 protocol.

**Desktop (web, three-column):** left nav (the four sections) · center content ·
right rail for the active insight/validation panel and a date scrubber. Charts
get more width; the marker table shows all markers at once instead of cards.

## Key screens

### Lab panel detail (the marquee screen)
- Header: panel date, source, "N markers".
- Each marker row: name · value+unit · a horizontal range bar (green band =
  reference range, dot = the value), and a `low/normal/high` chip. Out-of-range
  rows use a muted amber, **never alarming red**, except true critical values.
- Tapping a marker opens a Noom-style explainer: "Your {marker} is {value}
  {unit}, which is **{flag}** versus the lab's range {low–high}. A single result
  is often not meaningful on its own. This is not a diagnosis — discuss with a
  clinician." Plus the LOINC code and source of the range (report vs fallback).
- If any value is critical: a top banner (the only place red is used) —
  "One or more values need prompt clinical attention" — and marker interpretation
  is suppressed.

### Insight / hypothesis card
- Title + a confidence chip (C1–C5) with its label.
- Body always phrased as a question for C3 and below.
- "What else could explain this?" expander listing confounders.
- "Test this" button → opens the n-of-1 protocol (baseline, toggle, washout).
- Sources footnote for community templates.

### Onboarding (beginner-first)
- 4 short steps: welcome → consent to local storage of health data → "here's how
  each input works" (one card per: WHOOP, lab PDF, note, photo) → first entry.
- Mirrors Withings "Today's Missions": 2–3 tiny first actions with checkmarks.

## Visual system

- **Tone:** calm, clinical-but-warm. Generous whitespace, large type, one accent.
- **Color:** neutral background (#F7F8FA), ink text (#1A1D21). Accent teal
  (#2E7D74) for primary actions and "in range". Amber (#C77D2E) for out-of-range.
  Red (#C0392B) reserved exclusively for critical safety banners.
- **Confidence chips:** C5/C4 solid teal; C3 outlined; C2/C1 grey. The visual
  weight drops as certainty drops — low-confidence claims look quiet on purpose.
- **Type:** system font stack; 28/20/16/13 scale; numbers tabular.
- **Charts:** always shade the reference band; never a bare number without context.
- **Accessibility:** never encode state by color alone — pair every chip with a
  word (low/normal/high) and an icon.

## Implementation notes

- Web dashboard: Next.js (per ARCHITECTURE.md), reads the engine's JSON
  records/contexts. No server round-trip to anything but the local engine.
- The mobile experience can ship first as a Telegram Mini App (see the bot spec)
  reusing these screens, then as a PWA. Theme via Telegram `themeParams` so it
  looks native.
- The UI must render `evidence_class` and `confidence` from every record; it has
  no logic of its own for grading or safety — that lives in the engine.
