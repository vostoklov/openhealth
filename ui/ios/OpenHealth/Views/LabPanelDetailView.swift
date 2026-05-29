import SwiftUI

struct LabPanelDetailView: View {
    let panel: LabPanel
    @State private var selected: LabMarker?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.s3) {
                Text(panel.date)
                    .font(.system(size: 13)).foregroundStyle(Theme.inkSoft)

                ForEach(panel.markers) { marker in
                    Button { selected = marker } label: { markerRow(marker) }
                        .buttonStyle(.plain)
                }

                Text("A single out-of-range value is common and often not meaningful on its own. Trends over time matter more. This is not a diagnosis.")
                    .font(.system(size: 12))
                    .foregroundStyle(Theme.inkSoft)
                    .padding(.top, Theme.s2)
            }
            .padding(Theme.s4)
        }
        .background(Theme.background)
        .navigationTitle(panel.title)
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $selected) { marker in
            MarkerExplainerView(marker: marker)
                .presentationDetents([.medium, .large])
        }
    }

    private func markerRow(_ m: LabMarker) -> some View {
        Card {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack(alignment: .firstTextBaseline) {
                    Text(m.displayName)
                        .font(.system(size: 16, weight: .semibold)).foregroundStyle(Theme.ink)
                    Spacer()
                    Text(valueText(m))
                        .font(.system(size: 16, weight: .semibold)).foregroundStyle(Theme.ink)
                }
                RangeBar(value: m.value, low: m.referenceLow, high: m.referenceHigh, flag: m.flag)
                HStack(spacing: Theme.s2) {
                    Image(systemName: icon(m.flag)).font(.system(size: 12)).foregroundStyle(m.flag.color)
                    Text(m.flag.label).font(.system(size: 12, weight: .medium)).foregroundStyle(m.flag.color)
                    Spacer()
                    Text(rangeText(m)).font(.system(size: 12)).foregroundStyle(Theme.inkSoft)
                }
            }
        }
    }

    private func valueText(_ m: LabMarker) -> String {
        guard let v = m.value else { return "—" }
        return "\(trim(v)) \(m.unit ?? "")"
    }
    private func rangeText(_ m: LabMarker) -> String {
        let lo = m.referenceLow.map(trim) ?? "–"
        let hi = m.referenceHigh.map(trim) ?? "–"
        return "ref \(lo)–\(hi) · \(m.referenceSource)"
    }
    private func icon(_ flag: MarkerFlag) -> String {
        switch flag {
        case .normal: return "checkmark.circle.fill"
        case .low: return "arrow.down.circle.fill"
        case .high: return "arrow.up.circle.fill"
        case .unknown: return "questionmark.circle"
        }
    }
}

/// Cautious, plain-language explainer with an explicit clinician disclaimer.
struct MarkerExplainerView: View {
    let marker: LabMarker

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Theme.s4) {
                Text(headline)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(Theme.ink)
                    .padding(Theme.s4)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(marker.flag.color.opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))

                Text("A diagnosis should be made by a physician, not an app.")
                    .font(.system(size: 13)).foregroundStyle(Theme.inkSoft)

                if let note = marker.note {
                    Text(note).font(.system(size: 14)).foregroundStyle(Theme.ink)
                }

                VStack(alignment: .leading, spacing: Theme.s2) {
                    detailRow("Value", valueText)
                    detailRow("Reference", "\(marker.referenceLow.map(trim) ?? "–")–\(marker.referenceHigh.map(trim) ?? "–") (\(marker.referenceSource))")
                    if let si = marker.valueSI, let u = marker.siUnit {
                        detailRow("SI", "\(trim(si)) \(u)")
                    }
                    if let loinc = marker.loinc { detailRow("LOINC", loinc) }
                }
                Spacer()
            }
            .padding(Theme.s4)
        }
        .background(Theme.background)
    }

    private var headline: String {
        let v = marker.value.map(trim) ?? "—"
        return "Your \(marker.displayName) is \(v) \(marker.unit ?? ""), which is \(marker.flag.label) versus the lab's range."
    }
    private var valueText: String { "\(marker.value.map(trim) ?? "—") \(marker.unit ?? "")" }
    private func detailRow(_ k: String, _ v: String) -> some View {
        HStack {
            Text(k).font(.system(size: 13)).foregroundStyle(Theme.inkSoft)
            Spacer()
            Text(v).font(.system(size: 13, weight: .medium)).foregroundStyle(Theme.ink)
        }
    }
}

func trim(_ v: Double) -> String {
    v == v.rounded() ? String(Int(v)) : String(format: "%.1f", v)
}

#Preview {
    NavigationStack {
        LabPanelDetailView(panel: HealthStore().snapshot.panels.first
            ?? LabPanel(id: "x", date: "2024-06-01", title: "Panel", markers: []))
    }
}
