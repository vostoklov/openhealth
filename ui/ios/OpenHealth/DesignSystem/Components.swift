import SwiftUI

/// A soft surface card used across screens.
struct Card<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(Theme.s4)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.surface)
            .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                    .stroke(Theme.hairline, lineWidth: 1)
            )
    }
}

struct SectionHeader: View {
    let title: String
    var body: some View {
        Text(title)
            .font(.system(size: 20, weight: .semibold))
            .foregroundStyle(Theme.ink)
            .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Confidence chip. Visual weight drops as certainty drops — low-confidence
/// claims look quiet on purpose.
struct ConfidenceChip: View {
    let confidence: Confidence

    var body: some View {
        Text("\(confidence.rawValue) · \(confidence.label)")
            .font(.system(size: 12, weight: .semibold))
            .padding(.horizontal, Theme.s2)
            .padding(.vertical, Theme.s1)
            .foregroundStyle(foreground)
            .background(background)
            .overlay(
                Capsule().stroke(border, lineWidth: 1)
            )
            .clipShape(Capsule())
    }

    private var foreground: Color {
        switch confidence {
        case .c5, .c4: return .white
        case .c3: return Theme.accent
        case .c2, .c1: return Theme.inkSoft
        }
    }
    private var background: Color {
        switch confidence {
        case .c5, .c4: return Theme.accent
        case .c3: return .clear
        case .c2, .c1: return Theme.hairline.opacity(0.5)
        }
    }
    private var border: Color {
        switch confidence {
        case .c5, .c4: return .clear
        case .c3: return Theme.accent
        case .c2, .c1: return .clear
        }
    }
}

/// Horizontal range bar: green band = reference range, dot = the value.
/// State is paired with a word + icon, never color alone (accessibility).
struct RangeBar: View {
    let value: Double?
    let low: Double?
    let high: Double?
    let flag: MarkerFlag

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            ZStack(alignment: .leading) {
                Capsule().fill(Theme.hairline).frame(height: 6)
                Capsule().fill(flag.color.opacity(0.25))
                    .frame(width: max(0, bandWidth(w)), height: 6)
                    .offset(x: bandStart(w))
                Circle().fill(flag.color)
                    .frame(width: 12, height: 12)
                    .offset(x: dotX(w) - 6)
            }
            .frame(height: 12)
        }
        .frame(height: 12)
    }

    // Map the value/range onto the bar using a padded domain.
    private var domain: (Double, Double) {
        let lo = low ?? (value.map { $0 * 0.6 } ?? 0)
        let hi = high ?? (value.map { $0 * 1.4 } ?? 1)
        let lowBound = min(lo, value ?? lo)
        let highBound = max(hi, value ?? hi)
        let pad = (highBound - lowBound) * 0.15 + 0.0001
        return (lowBound - pad, highBound + pad)
    }
    private func pos(_ v: Double, _ w: CGFloat) -> CGFloat {
        let (a, b) = domain
        guard b > a else { return 0 }
        return CGFloat((v - a) / (b - a)) * w
    }
    private func bandStart(_ w: CGFloat) -> CGFloat { pos(low ?? domain.0, w) }
    private func bandWidth(_ w: CGFloat) -> CGFloat { pos(high ?? domain.1, w) - bandStart(w) }
    private func dotX(_ w: CGFloat) -> CGFloat {
        guard let v = value else { return 0 }
        return min(max(pos(v, w), 6), w - 6)
    }
}

/// Large hero tile: an oversized value on a calm gradient. The focal element of
/// the Today board (editorial, number-forward). Decorative gradient only.
struct HeroTile: View {
    let measurement: Measurement

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            Text(measurement.title.uppercased())
                .font(.system(size: 12, weight: .semibold))
                .tracking(0.8)
                .foregroundStyle(.white.opacity(0.85))
            Spacer(minLength: Theme.s4)
            Text(measurement.value)
                .font(.system(size: 48, weight: .bold, design: .rounded))
                .monospacedDigit()
                .foregroundStyle(.white)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            if let caption = measurement.caption {
                Text(caption)
                    .font(.system(size: 13))
                    .foregroundStyle(.white.opacity(0.85))
            }
        }
        .padding(Theme.s4)
        .frame(maxWidth: .infinity, minHeight: 180, alignment: .leading)
        .background(Theme.heroGradient(for: measurement.metric))
        .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
    }
}

/// Small board tile: number-forward measurement on a warm neutral surface.
struct BoardTile: View {
    let measurement: Measurement
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s1) {
            Text(measurement.title.uppercased())
                .font(.system(size: 11, weight: .semibold))
                .tracking(0.6)
                .foregroundStyle(Theme.inkSoft)
            Spacer(minLength: Theme.s3)
            Text(measurement.value)
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .monospacedDigit()
                .foregroundStyle(Theme.ink)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            if let caption = measurement.caption {
                Text(caption).font(.system(size: 12)).foregroundStyle(Theme.inkSoft)
            }
        }
        .padding(Theme.s4)
        .frame(maxWidth: .infinity, minHeight: 110, alignment: .leading)
        .background(tint)
        .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
    }
}

/// Prominent safety banner. The only place red is used.
struct SafetyBanner: View {
    let alert: SafetyAlert
    var body: some View {
        HStack(alignment: .top, spacing: Theme.s3) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.white)
            VStack(alignment: .leading, spacing: Theme.s1) {
                Text(alert.title).font(.system(size: 15, weight: .bold))
                Text(alert.message).font(.system(size: 13))
            }
            .foregroundStyle(.white)
        }
        .padding(Theme.s4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.danger)
        .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
    }
}
