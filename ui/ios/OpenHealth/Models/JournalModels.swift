import Foundation

// Journal-first intake. On mobile, the primary job is a fast daily check-in
// "about yesterday": a handful of lifestyle behaviours and felt-sense ratings,
// captured with minimal friction (WHOOP-style morning journal). The full,
// heavier analysis lives on desktop. Everything here is personal evidence,
// stored locally — no diagnosis, no cloud.

/// How a single behaviour is answered.
enum BehaviorKind: String, Codable {
    case yesNo      // tri-state: yes / no / unset
    case scale      // 1...5 felt-sense rating (energy, mood)
}

/// A logical grouping for the check-in sheet (mirrors WHOOP's sectioning).
enum JournalSection: String, Codable, CaseIterable, Identifiable {
    case sleep = "Sleep"
    case lifestyle = "Lifestyle"
    case status = "Status"
    var id: String { rawValue }
}

/// One trackable behaviour shown in the daily check-in. The starter set is
/// intentionally small to keep friction low.
struct JournalBehavior: Identifiable, Codable, Hashable {
    let id: String
    let prompt: String
    let icon: String            // SF Symbol name
    let kind: BehaviorKind
    let section: JournalSection
    var lowLabel: String? = nil   // scale only, e.g. "Drained"
    var highLabel: String? = nil  // scale only, e.g. "Energised"

    /// Starter behaviours: sleep-timing, food, training, light, energy, mood.
    /// Order here is the order shown in the check-in.
    static let starter: [JournalBehavior] = [
        JournalBehavior(id: "sleep_on_time", prompt: "Went to bed on your usual time?",
                        icon: "moon.stars", kind: .yesNo, section: .sleep),
        JournalBehavior(id: "screen_in_bed", prompt: "Used a screen in bed?",
                        icon: "iphone", kind: .yesNo, section: .sleep),
        JournalBehavior(id: "late_meal", prompt: "Ate a late or heavy meal?",
                        icon: "fork.knife", kind: .yesNo, section: .lifestyle),
        JournalBehavior(id: "alcohol", prompt: "Had any alcohol?",
                        icon: "wineglass", kind: .yesNo, section: .lifestyle),
        JournalBehavior(id: "trained", prompt: "Trained or moved a lot?",
                        icon: "figure.run", kind: .yesNo, section: .lifestyle),
        JournalBehavior(id: "morning_light", prompt: "Got morning daylight?",
                        icon: "sun.max", kind: .yesNo, section: .lifestyle),
        JournalBehavior(id: "energy", prompt: "Energy yesterday",
                        icon: "bolt.fill", kind: .scale, section: .status,
                        lowLabel: "Drained", highLabel: "Energised"),
        JournalBehavior(id: "mood", prompt: "Mood yesterday",
                        icon: "face.smiling", kind: .scale, section: .status,
                        lowLabel: "Low", highLabel: "Great")
    ]

    static func starter(id: String) -> JournalBehavior? {
        starter.first { $0.id == id }
    }
}

/// One value inside an entry. `bool` for yes/no behaviours, `scale` (1...5) for
/// ratings. Stored as a flat dictionary keyed by behaviour id.
enum JournalValue: Codable, Hashable {
    case bool(Bool)
    case scale(Int)

    private enum CodingKeys: String, CodingKey { case type, value }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        switch try c.decode(String.self, forKey: .type) {
        case "bool": self = .bool(try c.decode(Bool.self, forKey: .value))
        default: self = .scale(try c.decode(Int.self, forKey: .value))
        }
    }
    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case .bool(let b): try c.encode("bool", forKey: .type); try c.encode(b, forKey: .value)
        case .scale(let n): try c.encode("scale", forKey: .type); try c.encode(n, forKey: .value)
        }
    }

    var boolValue: Bool? { if case .bool(let b) = self { return b } else { return nil } }
    var scaleValue: Int? { if case .scale(let n) = self { return n } else { return nil } }
}

/// One day's check-in. `forDate` is the day being reflected on (yesterday);
/// `recordedAt` is the timestamp the entry was saved.
struct JournalEntry: Identifiable, Codable, Hashable {
    var id: String { dayKey }
    let dayKey: String              // "yyyy-MM-dd" of the reflected day
    let recordedAt: Date
    var values: [String: JournalValue]
    var note: String

    /// Number of answered behaviours (for a quick "how complete" readout).
    var answeredCount: Int { values.count }

    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.calendar = Calendar(identifier: .gregorian)
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    static func dayKey(for date: Date) -> String { dayFormatter.string(from: date) }

    /// A friendly label like "Sun, Jun 8" for the reflected day.
    var displayDay: String {
        guard let date = Self.dayFormatter.date(from: dayKey) else { return dayKey }
        let out = DateFormatter()
        out.locale = Locale(identifier: "en_US_POSIX")
        out.dateFormat = "EEE, MMM d"
        return out.string(from: date)
    }
}
