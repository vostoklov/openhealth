import SwiftUI

struct RootTabView: View {
    var body: some View {
        TabView {
            TodayView()
                .tabItem { Label("Today", systemImage: "sun.max") }
            TrendsView()
                .tabItem { Label("Trends", systemImage: "chart.xyaxis.line") }
            RecordsView()
                .tabItem { Label("Records", systemImage: "tray.full") }
            InsightsView()
                .tabItem { Label("Insights", systemImage: "lightbulb") }
        }
    }
}

#Preview {
    RootTabView().environment(HealthStore())
}
