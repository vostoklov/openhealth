import SwiftUI

struct InsightsView: View {
    @Environment(HealthStore.self) private var store

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.s4) {
                    Text("Hypotheses to explore, never conclusions. Each one shows how sure we are.")
                        .font(.system(size: 13)).foregroundStyle(Theme.inkSoft)

                    ForEach(store.snapshot.insights) { insight in
                        insightCard(insight)
                    }
                }
                .padding(Theme.s4)
            }
            .background(Theme.background)
            .navigationTitle("Insights")
        }
    }

    private func insightCard(_ insight: Insight) -> some View {
        Card {
            VStack(alignment: .leading, spacing: Theme.s3) {
                HStack {
                    Text(insight.title)
                        .font(.system(size: 17, weight: .semibold)).foregroundStyle(Theme.ink)
                    Spacer()
                    ConfidenceChip(confidence: insight.confidence)
                }

                // Phrase as a question at C3 and below.
                Text(insight.confidence.framesAsQuestion
                     ? "Possible pattern: \(insight.statement) What else could explain it?"
                     : insight.statement)
                    .font(.system(size: 15)).foregroundStyle(Theme.ink)

                if !insight.openQuestions.isEmpty {
                    VStack(alignment: .leading, spacing: Theme.s1) {
                        ForEach(insight.openQuestions, id: \.self) { q in
                            HStack(alignment: .top, spacing: Theme.s2) {
                                Text("•").foregroundStyle(Theme.inkSoft)
                                Text(q).font(.system(size: 13)).foregroundStyle(Theme.inkSoft)
                            }
                        }
                    }
                }

                if let validation = insight.suggestedValidation {
                    DisclosureGroup {
                        Text(validation).font(.system(size: 13)).foregroundStyle(Theme.inkSoft)
                            .padding(.top, Theme.s1)
                    } label: {
                        Text("How to test this")
                            .font(.system(size: 14, weight: .medium)).foregroundStyle(Theme.accent)
                    }
                    .tint(Theme.accent)
                }

                if !insight.sources.isEmpty {
                    Text("Sources: \(insight.sources.count)")
                        .font(.system(size: 11)).foregroundStyle(Theme.inkSoft)
                }
            }
        }
    }
}

#Preview {
    InsightsView().environment(HealthStore())
}
