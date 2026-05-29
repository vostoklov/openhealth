import SwiftUI

/// Original minimalist design system (see docs/design/ui-spec.md).
/// Calm, clinical-but-warm: neutral ground, one accent, red reserved for safety.
enum Theme {
    static let background = Color(hex: 0xF7F8FA)
    static let surface = Color.white
    static let ink = Color(hex: 0x1A1D21)
    static let inkSoft = Color(hex: 0x6B7178)
    static let hairline = Color(hex: 0xE6E8EB)

    static let accent = Color(hex: 0x2E7D74)   // teal: primary + "in range"
    static let warn = Color(hex: 0xC77D2E)      // amber: out of range
    static let danger = Color(hex: 0xC0392B)    // red: critical safety only

    // Spacing scale
    static let s1: CGFloat = 4
    static let s2: CGFloat = 8
    static let s3: CGFloat = 12
    static let s4: CGFloat = 16
    static let s5: CGFloat = 24
    static let s6: CGFloat = 32

    static let radius: CGFloat = 18
}

extension Color {
    init(hex: UInt32) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: 1
        )
    }
}

extension MarkerFlag {
    var color: Color {
        switch self {
        case .normal: return Theme.accent
        case .low, .high: return Theme.warn
        case .unknown: return Theme.inkSoft
        }
    }

    var label: String {
        switch self {
        case .normal: return "in range"
        case .low: return "low"
        case .high: return "high"
        case .unknown: return "no range"
        }
    }
}
