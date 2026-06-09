import SwiftUI

@main
struct OpenHealthApp: App {
    @State private var store = HealthStore()
    @State private var journal = JournalStore()

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environment(store)
                .environment(journal)
                .tint(Theme.accent)
                .preferredColorScheme(.dark)   // ships the dark Widget-Board surface
        }
    }
}
