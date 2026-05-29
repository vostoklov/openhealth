# OpenHealth iOS (SwiftUI)

A native, local-first iOS app for OpenHealth. Minimalist design grounded in
patterns from top shipped health apps (via Mobbin) and the project's
[UI spec](../../docs/design/ui-spec.md). It renders the engine's confidence
(C1–C5) and safety signals exactly as emitted — it never diagnoses.

## Screens

- **Today** — greeting, latest measurements, out-of-range review prompts, and
  any safety alerts pinned to the top. Daily check-in.
- **Trends** — Swift Charts line with the reference band shaded; reads "look for
  repeating patterns, not single days".
- **Records** — lab panels list → **Lab detail**: each marker with an in/out-of
  range bar and a cautious, Noom-style explainer (plain language + LOINC + an
  explicit "a diagnosis should be made by a physician" disclaimer).
- **Insights** — hypothesis cards with a confidence chip; C3 and below are
  phrased as questions, with an n-of-1 "how to test this" protocol.

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
│   ├── App/                    # @main entry
│   ├── Models/                 # records, store, sample loader
│   ├── DesignSystem/           # Theme + reusable components
│   ├── Views/                  # Today / Trends / Records / Lab detail / Insights
│   └── Resources/sample.json   # synthetic demo data
└── OpenHealthTests/            # model + confidence unit tests
```
