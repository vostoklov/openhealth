import SwiftUI

struct RootTabView: View {
    var body: some View {
        TabView {
            // Journal is the home tab: the mobile product's core daily job.
            JournalView()
                .tabItem { Label("Journal", systemImage: "square.and.pencil") }
            TodayView()
                .tabItem { Label("Today", systemImage: "sun.max") }
            TrendsView()
                .tabItem { Label("Trends", systemImage: "chart.xyaxis.line") }
            InsightsView()
                .tabItem { Label("Insights", systemImage: "lightbulb") }
        }
    }
}

#Preview {
    RootTabView()
        .environment(HealthStore())
        .environment(JournalStore())
}
