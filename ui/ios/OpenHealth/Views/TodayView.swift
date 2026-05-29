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

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.s5) {
                    // Safety alerts pinned to the very top.
                    ForEach(store.snapshot.alerts) { alert in
                        SafetyBanner(alert: alert)
                    }

                    // Out-of-range review prompts (calm, not alarming).
                    ForEach(store.snapshot.panels.filter { !$0.abnormal.isEmpty }) { panel in
                        reviewPrompt(panel)
                    }

                    SectionHeader(title: "Latest measurements")
                    LazyVGrid(columns: [GridItem(.flexible(), spacing: Theme.s3),
                                        GridItem(.flexible(), spacing: Theme.s3)],
                              spacing: Theme.s3) {
                        ForEach(store.snapshot.measurements) { m in
                            measurementTile(m)
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
            .navigationTitle("\(greeting), \(store.snapshot.greetingName)")
            .navigationBarTitleDisplayMode(.large)
        }
    }

    private func measurementTile(_ m: Measurement) -> some View {
        Card {
            VStack(alignment: .leading, spacing: Theme.s1) {
                Text(m.title).font(.system(size: 13)).foregroundStyle(Theme.inkSoft)
                Text(m.value).font(.system(size: 24, weight: .bold)).foregroundStyle(Theme.ink)
                if let c = m.caption {
                    Text(c).font(.system(size: 12)).foregroundStyle(Theme.inkSoft)
                }
            }
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
