import Foundation
import Observation

/// Loads the health snapshot. In production this reads the local engine's
/// exported JSON; here it loads a bundled synthetic sample so the app runs
/// standalone. No network, no cloud — local-first by design.
@Observable
final class HealthStore {
    var snapshot: HealthSnapshot = .empty

    init() {
        load()
    }

    func load() {
        if let url = Bundle.main.url(forResource: "sample", withExtension: "json"),
           let data = try? Data(contentsOf: url),
           let decoded = try? JSONDecoder().decode(HealthSnapshot.self, from: data) {
            snapshot = decoded
        }
    }
}

extension HealthSnapshot {
    static let empty = HealthSnapshot(
        greetingName: "there",
        measurements: [],
        panels: [],
        trends: [],
        insights: [],
        alerts: []
    )
}
