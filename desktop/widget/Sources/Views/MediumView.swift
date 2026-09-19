// MediumView.swift
//
// Purpose    : systemMedium widget layout — left status column, right up to
//              three device rows (name, place, age; a stale row is greyed out
//              and its place reads "unknown", never its last known place).
// Inputs     : WidgetEntry.
// Outputs    : A SwiftUI View for the medium widget family.
// Constraints: Locked/Down states show a full-width message, no device rows.
//              `embedded` is set by LargeView, which supplies its own action
//              row and its own footer notice: without it the large family
//              renders Poll now/Open twice and prints the notice mid-layout
//              instead of in the footer (widget.md § Behaviour).

import SwiftUI
import WidgetKit

struct MediumView: View {
    let entry: WidgetEntry
    var embedded: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if entry.state == .locked {
                HStack {
                    Image(systemName: "lock.fill")
                    Text("Locked")
                }
            } else if entry.state == .down {
                Text("Find+ is not running")
            } else {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack {
                            Circle().fill(dotColour(entry.state)).frame(width: 10, height: 10)
                            Text(stateLabel(entry.state)).font(.headline)
                        }
                        if let device = entry.response?.devices.first {
                            Text(formatAge(minutes: device.age_minutes)).font(.caption)
                        }
                        if !embedded {
                            HStack {
                                Button(intent: PollNowIntent()) {
                                    Label("Poll now", systemImage: "arrow.clockwise")
                                }
                                .disabled(entry.state == .locked || entry.state == .down)
                                Button(intent: OpenFindPlusIntent()) {
                                    Label("Open", systemImage: "arrow.up.right.square")
                                }
                            }
                        }
                    }
                    Spacer()
                    VStack(alignment: .leading, spacing: 3) {
                        ForEach(Array((entry.response?.devices ?? []).prefix(3)), id: \.device_id) { device in
                            deviceRow(device)
                        }
                    }
                }
            }
            if !embedded {
                Spacer()
                NoticeFooter(entry: entry)
            }
        }
    }

    private func deviceRow(_ device: WidgetDevice) -> some View {
        let staleAfter = entry.staleAfterMinutes
        return HStack {
            Text(device.name).font(.caption)
            Text(device.placeText(staleAfter: staleAfter))
                .font(.caption2)
                .foregroundStyle(.secondary)
            if device.isStale(after: staleAfter) {
                Text("no fix for \(device.age_minutes / 60) h")
                    .font(.caption2)
                    .foregroundStyle(Color.dotGrey)
            } else {
                Text(formatAge(minutes: device.age_minutes)).font(.caption2)
            }
        }
    }
}
