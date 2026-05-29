import SwiftUI
import Charts

struct TrendsView: View {
    @Environment(HealthStore.self) private var store
    @State private var selectedMetric: String?

    private var trend: Trend? {
        store.snapshot.trends.first { $0.metric == selectedMetric } ?? store.snapshot.trends.first
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.s4) {
                    if !store.snapshot.trends.isEmpty {
                        Picker("Metric", selection: Binding(
                            get: { trend?.metric ?? "" },
                            set: { selectedMetric = $0 }
                        )) {
                            ForEach(store.snapshot.trends) { t in
                                Text(t.title).tag(t.metric)
                            }
                        }
                        .pickerStyle(.segmented)
                    }

                    if let t = trend {
                        Card {
                            VStack(alignment: .leading, spacing: Theme.s3) {
                                Text(t.title).font(.system(size: 18, weight: .semibold))
                                    .foregroundStyle(Theme.ink)
                                chart(t)
                                    .frame(height: 200)
                                Text(readout(t))
                                    .font(.system(size: 13)).foregroundStyle(Theme.inkSoft)
                            }
                        }
                    } else {
                        Text("No trends yet.").foregroundStyle(Theme.inkSoft)
                    }
                }
                .padding(Theme.s4)
            }
            .background(Theme.background)
            .navigationTitle("Trends")
        }
    }

    @ViewBuilder
    private func chart(_ t: Trend) -> some View {
        Chart {
            if let lo = t.referenceLow, let hi = t.referenceHigh {
                RectangleMark(
                    yStart: .value("low", lo),
                    yEnd: .value("high", hi)
                )
                .foregroundStyle(Theme.accent.opacity(0.10))
            }
            ForEach(t.points) { p in
                LineMark(x: .value("Day", p.date), y: .value(t.unit, p.value))
                    .foregroundStyle(Theme.accent)
                    .interpolationMethod(.catmullRom)
                PointMark(x: .value("Day", p.date), y: .value(t.unit, p.value))
                    .foregroundStyle(Theme.accent)
            }
        }
        .chartYScale(domain: yDomain(t))
    }

    private func yDomain(_ t: Trend) -> ClosedRange<Double> {
        let values = t.points.map(\.value) + [t.referenceLow, t.referenceHigh].compactMap { $0 }
        let lo = (values.min() ?? 0) * 0.9
        let hi = (values.max() ?? 1) * 1.1
        return lo...max(hi, lo + 1)
    }

    private func readout(_ t: Trend) -> String {
        guard let last = t.points.last?.value else { return "" }
        let inRange: Bool = {
            if let lo = t.referenceLow, last < lo { return false }
            if let hi = t.referenceHigh, last > hi { return false }
            return true
        }()
        let state = inRange ? "within your typical range" : "outside your typical range"
        return "Latest: \(trim(last)) \(t.unit) — \(state). Look for repeating patterns, not single days."
    }
}

#Preview {
    TrendsView().environment(HealthStore())
}
