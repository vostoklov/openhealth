# OpenHealth iOS (SwiftUI)

A native, local-first iOS app for OpenHealth. **Journal-first**: the mobile
product's core job is a fast daily lifestyle/feeling check-in; recovery and
strain are shown as a glanceable summary, and the heavier analysis lives on
desktop. Dark "Widget Board" surface from the
[style bible](../../docs/design/style-bible.md), with recovery color-coding
(green/yellow/red) matching the web dashboard. It renders the engine's
confidence (C1–C5) and safety signals exactly as emitted — it never diagnoses.

## Screens (tabs: Journal · Today · Trends · Insights)

- **Journal** (home) — a fast check-in "about yesterday": a small starter set of
  behaviours (sleep timing, late meal, alcohol, training, morning light) as
  yes/no rows plus 1–5 energy/mood ratings and a free note. Saved locally with a
  timestamp; recent entries listed below. Minimal-friction, WHOOP-style.
- **Today** — recovery/strain summary: a color-coded recovery ring (green ≥67 /
  yellow 34–66 / red <34), HRV·Strain·RHR·Sleep tiles, "Ready for today"
  readiness, and **Doctor Context** (a mood read on recovery). Safety alerts and
  out-of-range lab review prompts pin to the top. Observational, never advice.
- **Trends** — Swift Charts line with the reference band shaded; reads "look for
  repeating patterns, not single days".
- **Insights** — hypothesis cards with a confidence chip; C3 and below are
  phrased as questions, with an n-of-1 "how to test this" protocol.

The **Records / Lab detail** screen (markers with an in/out-of-range bar and a
cautious explainer) is reachable from Today's review prompts; it is not a
top-level tab (the design keeps nav to four destinations).

## Local journal storage

Journal entries persist to `journal.json` in the app's Documents directory
(`JournalStore`). One entry per reflected day; re-saving overwrites it. No
network, no cloud.

## Requirements

- Xcode 16+ (built and verified against Xcode 26 / iOS 17+ deployment target)
- [XcodeGen](https://github.com/yonaskolb/XcodeGen) (`brew install xcodegen`)

## Build & run

```bash
cd ui/ios
xcodegen generate        # produces OpenHealth.xcodeproj from project.yml
open OpenHealth.xcodeproj # then Run (Cmd+R) on a simulator
```

CLI build (no simulator runtime needed to compile):

```bash
xcodebuild build -project OpenHealth.xcodeproj -target OpenHealth \
  -sdk iphonesimulator -configuration Debug CODE_SIGNING_ALLOWED=NO
```

Unit tests (`OpenHealthTests`) run through the Xcode scheme or CI (Xcode Cloud)
where an iOS simulator runtime is installed.

## Data

The app loads a bundled synthetic snapshot (`OpenHealth/Resources/sample.json`)
whose shape mirrors the engine's exported records (see
[`HealthModels.swift`](OpenHealth/Models/HealthModels.swift)). To wire it to a
real local engine export, replace the loader in
[`HealthStore.swift`](OpenHealth/Models/HealthStore.swift). No network, no cloud.

## Project layout

```
ui/ios/
├── project.yml                 # XcodeGen spec (project is generated, gitignored)
├── OpenHealth/
│   ├── App/                    # @main entry (dark color scheme)
│   ├── Models/                 # snapshot records + loader; journal models + local store
│   ├── DesignSystem/           # Theme (dark + recovery zones) + reusable components
│   ├── Views/                  # Journal (home) / Today / Trends / Records / Lab detail / Insights
│   └── Resources/sample.json   # synthetic demo data
└── OpenHealthTests/            # model + confidence unit tests
```
