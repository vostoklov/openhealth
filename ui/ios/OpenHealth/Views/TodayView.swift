import SwiftUI

struct TodayView: View {
    @Environment(HealthStore.self) private var store

    private var greeting: String {
        let hour = Calendar.current.component(.hour, from: Date())
        switch hour {
        case 5..<12: return "Good morning"
        case 12..<18: return "Good afternoon"
        default: return "Good evening"
        }
    }

    private let boardTints = [Theme.sand, Theme.sage, Theme.mist]

    // The recovery metric drives the focal ring; the rest fill the board.
    private var recoveryMeasurement: Measurement? {
        store.snapshot.measurements.first { $0.metric == "recovery" }
    }
    private var boardMeasurements: [Measurement] {
        store.snapshot.measurements.filter { $0.metric != "recovery" }
    }

    /// Progress 0...1. Percentage metrics map directly; others fall back to a
    /// neutral half-fill so the ring still reads as a summary.
    private func ringProgress(_ m: Measurement) -> Double {
        guard let n = leadingNumber(m.value) else { return 0.5 }
        return m.value.contains("%") ? n / 100 : min(n / 100, 1)
    }
    private func ringTint(_ m: Measurement) -> Color {
        ringProgress(m) >= 0.5 ? Theme.accent : Theme.warn
    }
    /// Observational readout — describes, does not prescribe.
    private func ringReadout(_ m: Measurement) -> String {
        let p = ringProgress(m)
        if p >= 0.66 { return "In your usual range for \(m.title.lowercased())." }
        if p >= 0.5 { return "A middling \(m.title.lowercased()) reading — nothing unusual." }
        return "Lower than your usual \(m.title.lowercased()). Worth noting, not alarming."
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.s5) {
                    // Editorial greeting headline (serif display).
                    VStack(alignment: .leading, spacing: 2) {
                        Text(greeting)
                            .font(.system(size: 22, weight: .regular, design: .serif))
                            .foregroundStyle(Theme.inkSoft)
                        Text(store.snapshot.greetingName)
                            .font(.system(size: 40, weight: .bold, design: .serif))
                            .foregroundStyle(Theme.ink)
                    }
                    .padding(.top, Theme.s2)

                    // Safety alerts pinned to the very top.
                    ForEach(store.snapshot.alerts) { alert in
                        SafetyBanner(alert: alert)
                    }

                    // Out-of-range review prompts (calm, not alarming).
                    ForEach(store.snapshot.panels.filter { !$0.abnormal.isEmpty }) { panel in
                        reviewPrompt(panel)
                    }

                    // Recovery ring as the focal element, then a board of the rest.
                    if let ring = recoveryMeasurement {
                        RingCard(
                            title: ring.title,
                            progress: ringProgress(ring),
                            centerValue: ring.value,
                            tint: ringTint(ring),
                            readout: ringReadout(ring)
                        )
                    } else if let hero = store.snapshot.measurements.first {
                        HeroTile(measurement: hero)
                    }
                    LazyVGrid(columns: [GridItem(.flexible(), spacing: Theme.s3),
                                        GridItem(.flexible(), spacing: Theme.s3)],
                              spacing: Theme.s3) {
                        ForEach(Array(boardMeasurements.enumerated()), id: \.element.id) { idx, m in
                            BoardTile(measurement: m, tint: boardTints[idx % boardTints.count])
                        }
                    }

                    NavigationLink {
                        CheckInView()
                    } label: {
                        Text("Daily check-in")
                            .font(.system(size: 16, weight: .semibold))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, Theme.s3)
                            .background(Theme.accent)
                            .foregroundStyle(.white)
                            .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
                    }
                }
                .padding(Theme.s4)
            }
            .background(Theme.background)
            .navigationBarHidden(true)
        }
    }

    private func reviewPrompt(_ panel: LabPanel) -> some View {
        NavigationLink {
            LabPanelDetailView(panel: panel)
        } label: {
            Card {
                VStack(alignment: .leading, spacing: Theme.s2) {
                    HStack {
                        Image(systemName: "info.circle").foregroundStyle(Theme.warn)
                        Text("Some markers to review").font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(Theme.ink)
                        Spacer()
                        Image(systemName: "chevron.right").foregroundStyle(Theme.inkSoft)
                    }
                    Text(panel.abnormal.map { "\($0.displayName) \($0.flag.label)" }.joined(separator: ", "))
                        .font(.system(size: 13)).foregroundStyle(Theme.inkSoft)
                    Text("A prompt to review with a clinician, not a diagnosis.")
                        .font(.system(size: 12)).foregroundStyle(Theme.inkSoft)
                }
            }
        }
        .buttonStyle(.plain)
    }
}

/// Minimal mood check-in (mirrors the engine's /checkin intake).
struct CheckInView: View {
    @Environment(\.dismiss) private var dismiss
    private let options = ["Great", "Good", "Okay", "Low"]
    @State private var picked: String?

    var body: some View {
        VStack(spacing: Theme.s5) {
            Text("How are you feeling right now?")
                .font(.system(size: 20, weight: .semibold))
                .multilineTextAlignment(.center)
            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: Theme.s3) {
                ForEach(options, id: \.self) { opt in
                    Button {
                        picked = opt
                    } label: {
                        Text(opt)
                            .font(.system(size: 16, weight: .medium))
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, Theme.s4)
                            .background(picked == opt ? Theme.accent : Theme.surface)
                            .foregroundStyle(picked == opt ? .white : Theme.ink)
                            .overlay(RoundedRectangle(cornerRadius: Theme.radius).stroke(Theme.hairline))
                            .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
                    }
                }
            }
            if picked != nil {
                Button("Save") { dismiss() }
                    .font(.system(size: 16, weight: .semibold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.s3)
                    .background(Theme.accent).foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
            }
            Spacer()
        }
        .padding(Theme.s4)
        .background(Theme.background)
        .navigationTitle("Check-in")
        .navigationBarTitleDisplayMode(.inline)
    }
}

#Preview {
    TodayView().environment(HealthStore())
}
