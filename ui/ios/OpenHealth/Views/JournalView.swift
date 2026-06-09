import SwiftUI

/// The home screen (first tab). A fast daily check-in "about yesterday":
/// a small set of lifestyle behaviours + felt-sense ratings, captured inline
/// with minimal friction. This is the mobile product's core job; deeper
/// analysis lives on desktop. Personal evidence, stored locally, never a
/// diagnosis.
struct JournalView: View {
    @Environment(JournalStore.self) private var journal

    private let behaviors = JournalBehavior.starter

    // The day being reflected on (yesterday) and its existing entry, if any.
    private var reflectedDate: Date { JournalStore.reflectedDay() }
    private var dayKey: String { JournalEntry.dayKey(for: reflectedDate) }
    private var existing: JournalEntry? { journal.entry(forDayKey: dayKey) }

    // Working draft, seeded from any existing entry for the day.
    @State private var values: [String: JournalValue] = [:]
    @State private var note: String = ""
    @State private var didSave = false
    @State private var loadedKey: String?

    private var dayLabel: String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "EEEE, MMM d"
        return f.string(from: reflectedDate)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: Theme.s5) {
                    header

                    // Check-in card, grouped by section like a morning journal.
                    VStack(spacing: Theme.s4) {
                        ForEach(JournalSection.allCases) { section in
                            let items = behaviors.filter { $0.section == section }
                            if !items.isEmpty {
                                sectionBlock(section, items)
                            }
                        }
                        noteBlock
                        saveButton
                    }

                    historyBlock

                    Text("A place to notice patterns, not a diagnosis. Anything worrying goes to a clinician.")
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.inkDim)
                        .padding(.top, Theme.s1)
                }
                .padding(Theme.s4)
            }
            .background(Theme.background.ignoresSafeArea())
            .navigationBarHidden(true)
            .scrollDismissesKeyboard(.interactively)
        }
        .onAppear(perform: seedIfNeeded)
    }

    // MARK: - Header

    private var header: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            Text("JOURNAL")
                .font(.system(size: 11, weight: .semibold))
                .tracking(1.2)
                .foregroundStyle(Theme.inkSoft)
            Text("What happened\nyesterday?")
                .font(.system(size: 32, weight: .bold, design: .serif))
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: Theme.s2) {
                Text(dayLabel)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Theme.inkSoft)
                if existing != nil {
                    Text("· logged")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Theme.zoneGreen)
                }
            }
        }
        .padding(.top, Theme.s2)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - Section block

    private func sectionBlock(_ section: JournalSection, _ items: [JournalBehavior]) -> some View {
        Card {
            VStack(alignment: .leading, spacing: Theme.s3) {
                Text(section.rawValue.uppercased())
                    .font(.system(size: 10, weight: .semibold))
                    .tracking(0.8)
                    .foregroundStyle(Theme.inkDim)
                ForEach(Array(items.enumerated()), id: \.element.id) { idx, behavior in
                    if idx > 0 { Divider().overlay(Theme.hairline) }
                    behaviorRow(behavior)
                }
            }
        }
    }

    @ViewBuilder
    private func behaviorRow(_ behavior: JournalBehavior) -> some View {
        switch behavior.kind {
        case .yesNo:
            YesNoRow(
                behavior: behavior,
                value: values[behavior.id]?.boolValue,
                onPick: { picked in setBool(behavior.id, picked) }
            )
        case .scale:
            ScaleRow(
                behavior: behavior,
                value: values[behavior.id]?.scaleValue,
                onPick: { n in setScale(behavior.id, n) }
            )
        }
    }

    // MARK: - Note + save

    private var noteBlock: some View {
        Card {
            VStack(alignment: .leading, spacing: Theme.s2) {
                Text("NOTE")
                    .font(.system(size: 10, weight: .semibold))
                    .tracking(0.8)
                    .foregroundStyle(Theme.inkDim)
                TextField("Anything else worth remembering…", text: $note, axis: .vertical)
                    .lineLimit(2...5)
                    .font(.system(size: 15))
                    .foregroundStyle(Theme.ink)
                    .tint(Theme.accent)
            }
        }
    }

    private var saveButton: some View {
        Button(action: save) {
            HStack {
                if didSave {
                    Image(systemName: "checkmark")
                    Text("Saved")
                } else {
                    Text(existing == nil ? "Save journal" : "Update journal")
                }
            }
            .font(.system(size: 16, weight: .semibold))
            .frame(maxWidth: .infinity)
            .padding(.vertical, Theme.s3 + 2)
            .foregroundStyle(didSave ? Theme.zoneGreen : Theme.background)
            .background(didSave ? Theme.surface : Theme.zoneGreen)
            .overlay(
                RoundedRectangle(cornerRadius: Theme.radius, style: .continuous)
                    .stroke(didSave ? Theme.zoneGreen : .clear, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous))
        }
        .disabled(values.isEmpty && note.isEmpty)
        .opacity(values.isEmpty && note.isEmpty ? 0.5 : 1)
    }

    // MARK: - History

    @ViewBuilder
    private var historyBlock: some View {
        let past = journal.recent.filter { $0.dayKey != dayKey }
        if !past.isEmpty {
            VStack(alignment: .leading, spacing: Theme.s3) {
                Text("RECENT")
                    .font(.system(size: 10, weight: .semibold))
                    .tracking(0.8)
                    .foregroundStyle(Theme.inkDim)
                ForEach(past.prefix(7)) { entry in
                    HistoryRow(entry: entry)
                }
            }
            .padding(.top, Theme.s2)
        }
    }

    // MARK: - State

    private func seedIfNeeded() {
        guard loadedKey != dayKey else { return }
        loadedKey = dayKey
        if let e = existing {
            values = e.values
            note = e.note
        } else {
            values = [:]
            note = ""
        }
        didSave = false
    }

    private func setBool(_ id: String, _ picked: Bool) {
        if values[id]?.boolValue == picked {
            values.removeValue(forKey: id)   // tap-again clears (tri-state)
        } else {
            values[id] = .bool(picked)
        }
        didSave = false
    }

    private func setScale(_ id: String, _ n: Int) {
        if values[id]?.scaleValue == n {
            values.removeValue(forKey: id)
        } else {
            values[id] = .scale(n)
        }
        didSave = false
    }

    private func save() {
        let entry = JournalEntry(
            dayKey: dayKey,
            recordedAt: Date(),
            values: values,
            note: note.trimmingCharacters(in: .whitespacesAndNewlines)
        )
        journal.save(entry)
        withAnimation(.easeOut(duration: 0.2)) { didSave = true }
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }
}

// MARK: - Rows

/// A yes/no behaviour as a row with X / ✓ segmented buttons (WHOOP-style).
private struct YesNoRow: View {
    let behavior: JournalBehavior
    let value: Bool?
    let onPick: (Bool) -> Void

    var body: some View {
        HStack(spacing: Theme.s3) {
            Image(systemName: behavior.icon)
                .font(.system(size: 15))
                .foregroundStyle(Theme.inkSoft)
                .frame(width: 22)
            Text(behavior.prompt)
                .font(.system(size: 15))
                .foregroundStyle(Theme.ink)
            Spacer(minLength: Theme.s3)
            HStack(spacing: Theme.s2) {
                pill(systemName: "xmark", active: value == false, tint: Theme.danger) { onPick(false) }
                pill(systemName: "checkmark", active: value == true, tint: Theme.zoneGreen) { onPick(true) }
            }
        }
    }

    private func pill(systemName: String, active: Bool, tint: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 13, weight: .bold))
                .frame(width: 38, height: 32)
                .foregroundStyle(active ? Theme.background : Theme.inkSoft)
                .background(active ? tint : Theme.surfaceAlt)
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(Theme.hairlineStrong, lineWidth: active ? 0 : 1)
                )
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

/// A 1...5 felt-sense rating as a row of selectable chips.
private struct ScaleRow: View {
    let behavior: JournalBehavior
    let value: Int?
    let onPick: (Int) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s2) {
            HStack(spacing: Theme.s3) {
                Image(systemName: behavior.icon)
                    .font(.system(size: 15))
                    .foregroundStyle(Theme.inkSoft)
                    .frame(width: 22)
                Text(behavior.prompt)
                    .font(.system(size: 15))
                    .foregroundStyle(Theme.ink)
                Spacer()
            }
            HStack(spacing: Theme.s2) {
                ForEach(1...5, id: \.self) { n in
                    Button { onPick(n) } label: {
                        Text("\(n)")
                            .font(.system(size: 15, weight: .semibold, design: .rounded))
                            .monospacedDigit()
                            .frame(maxWidth: .infinity)
                            .frame(height: 36)
                            .foregroundStyle(value == n ? Theme.background : Theme.inkSoft)
                            .background(value == n ? Theme.accent : Theme.surfaceAlt)
                            .overlay(
                                RoundedRectangle(cornerRadius: 8, style: .continuous)
                                    .stroke(Theme.hairlineStrong, lineWidth: value == n ? 0 : 1)
                            )
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }
            }
            if let lo = behavior.lowLabel, let hi = behavior.highLabel {
                HStack {
                    Text(lo); Spacer(); Text(hi)
                }
                .font(.system(size: 11))
                .foregroundStyle(Theme.inkDim)
                .padding(.leading, 22 + Theme.s3)
            }
        }
    }
}

/// A compact past-entry row: day, a few logged-behaviour glyphs, mood/energy.
private struct HistoryRow: View {
    let entry: JournalEntry

    private func glyph(_ id: String) -> String? {
        JournalBehavior.starter(id: id)?.icon
    }

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: Theme.s2) {
                HStack {
                    Text(entry.displayDay)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Theme.ink)
                    Spacer()
                    Text("\(entry.answeredCount) logged")
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.inkDim)
                }
                HStack(spacing: Theme.s3) {
                    ForEach(Array(entry.values.keys.sorted()), id: \.self) { key in
                        if let g = glyph(key) {
                            let v = entry.values[key]
                            HStack(spacing: 3) {
                                Image(systemName: g)
                                    .font(.system(size: 11))
                                if let b = v?.boolValue {
                                    Image(systemName: b ? "checkmark" : "xmark")
                                        .font(.system(size: 9, weight: .bold))
                                        .foregroundStyle(b ? Theme.zoneGreen : Theme.danger)
                                } else if let n = v?.scaleValue {
                                    Text("\(n)").font(.system(size: 11, weight: .semibold)).monospacedDigit()
                                }
                            }
                            .foregroundStyle(Theme.inkSoft)
                        }
                    }
                }
                if !entry.note.isEmpty {
                    Text(entry.note)
                        .font(.system(size: 12))
                        .foregroundStyle(Theme.inkSoft)
                        .lineLimit(2)
                }
            }
        }
    }
}

#Preview {
    JournalView().environment(JournalStore())
}
