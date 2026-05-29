import SwiftUI

@main
struct OpenHealthApp: App {
    @State private var store = HealthStore()

    var body: some Scene {
        WindowGroup {
            RootTabView()
                .environment(store)
                .tint(Theme.accent)
        }
    }
}
