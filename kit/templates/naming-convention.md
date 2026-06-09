# File naming convention (template)

Predictable names = your agent (and future you) can find anything. Keep it boring
and consistent.

## Pattern
`<area>__<kind>__<subject>__<YYYY-MM-DD>.<ext>`

- **area**: pulse | sleep | cycle | body | metabolic | skin | labs | mental | notes
- **kind**: export | lab | note | protocol | insight | photo | research
- **subject**: short slug (lowercase-with-dashes)
- **date**: the date the data is *about* (not when you saved it)

## Examples
- `labs__lab__blood-panel__2024-06-01.pdf`
- `sleep__export__apple-health__2026-06-09.zip`
- `body__protocol__late-coffee-vs-sleep__2026-06-10.md`
- `pulse__insight__weekend-recovery-dip__2026-06-12.md`

## Rules
- One subject per file. Dates in ISO (`YYYY-MM-DD`) so they sort.
- Raw exports stay immutable — never edit an archived source; derive new files.
- No personal names / emails / secrets in filenames.
