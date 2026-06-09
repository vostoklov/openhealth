import Foundation
import Observation

/// Local-first journal storage. Entries persist to a single JSON file in the
/// app's Documents directory — no network, no cloud (AGENTS.md: prefer local
/// storage). One entry per reflected day; re-saving the same day overwrites it.
@Observable
final class JournalStore {
    private(set) var entries: [JournalEntry] = []

    private let fileURL: URL
    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.outputFormatting = [.prettyPrinted, .sortedKeys]
        e.dateEncodingStrategy = .iso8601
        return e
    }()
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }()

    init(fileName: String = "journal.json") {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        fileURL = docs.appendingPathComponent(fileName)
        load()
    }

    // MARK: - Queries

    /// The reflected day for a morning check-in is "yesterday" relative to now.
    static func reflectedDay(from now: Date = Date()) -> Date {
        Calendar.current.date(byAdding: .day, value: -1, to: now) ?? now
    }

    func entry(forDayKey key: String) -> JournalEntry? {
        entries.first { $0.dayKey == key }
    }

    /// Most recent entries first.
    var recent: [JournalEntry] {
        entries.sorted { $0.dayKey > $1.dayKey }
    }

    // MARK: - Mutations

    /// Insert or replace the entry for its reflected day, then persist.
    func save(_ entry: JournalEntry) {
        entries.removeAll { $0.dayKey == entry.dayKey }
        entries.append(entry)
        persist()
    }

    func delete(dayKey: String) {
        entries.removeAll { $0.dayKey == dayKey }
        persist()
    }

    // MARK: - Persistence

    private func load() {
        guard let data = try? Data(contentsOf: fileURL) else { return }
        if let decoded = try? decoder.decode([JournalEntry].self, from: data) {
            entries = decoded
        }
    }

    private func persist() {
        guard let data = try? encoder.encode(entries) else { return }
        try? data.write(to: fileURL, options: [.atomic])
    }
}
